import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import Downloader from "../../src/components/Downloader.svelte";
import { inspectOk, job } from "./fixtures";

type Handler = (body: unknown) => { status: number; json: unknown };

function mockFetch(routes: Record<string, Handler>) {
  const fetchMock = vi.fn(async (input: Request | string) => {
    const req = input instanceof Request ? input : new Request(input);
    const path = new URL(req.url, "http://localhost").pathname;
    const handler = routes[`${req.method} ${path}`];
    if (!handler) return new Response("{}", { status: 404 });
    const body = req.method === "GET" ? undefined : await req.json();
    const { status, json } = handler(body);
    return new Response(JSON.stringify(json), {
      status,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

class FakeEventSource {
  static last: FakeEventSource | null = null;
  listeners = new Map<string, (e: MessageEvent) => void>();
  onerror: (() => void) | null = null;
  closed = false;
  constructor(readonly url: string) {
    FakeEventSource.last = this;
  }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    this.listeners.set(type, fn);
  }
  emit(data: unknown) {
    this.listeners.get("job")?.(new MessageEvent("job", { data: JSON.stringify(data) }));
  }
  close() {
    this.closed = true;
  }
}

const URL_IN = "https://www.youtube.com/watch?v=abc";

async function analyze(url = URL_IN) {
  const input = screen.getByLabelText("Enlace del vídeo");
  await fireEvent.input(input, { target: { value: url } });
  await fireEvent.click(screen.getByRole("button", { name: "Analizar" }));
}

describe("Downloader", () => {
  beforeEach(() => {
    FakeEventSource.last = null;
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("asks for a URL when the field is empty", async () => {
    const fetchMock = mockFetch({});
    render(Downloader);
    await fireEvent.click(screen.getByRole("button", { name: "Analizar" }));
    const input = screen.getByLabelText("Enlace del vídeo");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText("Escribe o pega un enlace.")).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows metadata as text and only real qualities", async () => {
    mockFetch({ "POST /api/v1/inspect": () => ({ status: 200, json: inspectOk }) });
    const { container } = render(Downloader);
    await analyze();
    const heading = await screen.findByRole("heading", { level: 2 });
    expect(heading.textContent).toBe("Hola <img src=x onerror=alert(1)>");
    expect(container.querySelector("h2 img")).toBeNull(); // escaped, not rendered
    const options = screen.getAllByRole("radio", { name: /1080p|2160p|Solo audio/ });
    expect(options).toHaveLength(3);
    expect((screen.getByRole("radio", { name: /1080p/ }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("radio", { name: /2160p/ }) as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText(/Supera el límite/)).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(heading));
  });

  it("explains unsupported sites on the field", async () => {
    mockFetch({
      "POST /api/v1/inspect": () => ({
        status: 422,
        json: { error: { code: "UNSUPPORTED_SITE", message: "x", retryable: false } },
      }),
    });
    render(Downloader);
    await analyze("https://example.org/v");
    expect(await screen.findByText("Este sitio no es compatible")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("offers a retry for temporary platform errors", async () => {
    let calls = 0;
    mockFetch({
      "POST /api/v1/inspect": () =>
        ++calls === 1
          ? {
              status: 503,
              json: { error: { code: "PLATFORM_BLOCKED", message: "x", retryable: true } },
            }
          : { status: 200, json: inspectOk },
    });
    render(Downloader);
    await analyze();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("rechazado la petición temporalmente");
    await fireEvent.click(screen.getByRole("button", { name: "Intentar de nuevo" }));
    expect(await screen.findByRole("heading", { level: 2 })).toBeTruthy();
    expect(calls).toBe(2);
  });

  it("downloads with progress and hands the file to the browser", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign, search: "" });
    const fetchMock = mockFetch({
      "POST /api/v1/inspect": () => ({ status: 200, json: inspectOk }),
      "POST /api/v1/downloads": () => ({ status: 202, json: job() }),
    });
    render(Downloader);
    await analyze();
    await fireEvent.click(await screen.findByRole("button", { name: "Descargar" }));
    await waitFor(() => expect(FakeEventSource.last).not.toBeNull());
    const sent = await (fetchMock.mock.calls.at(-1)?.[0] as Request).clone().json();
    expect(sent).toEqual({ url: URL_IN, option_id: "v1080" });

    FakeEventSource.last?.emit(
      job({
        phase: "downloading",
        version: 2,
        progress: { downloaded: 0, total: null, total_is_estimate: false },
      }),
    );
    const bar = await screen.findByRole("progressbar");
    expect(bar.hasAttribute("value")).toBe(false); // unknown total → indeterminate

    FakeEventSource.last?.emit(
      job({
        phase: "downloading",
        version: 3,
        progress: { downloaded: 42, total: 100, total_is_estimate: false },
      }),
    );
    expect(await screen.findByText("Descargando… 42 %")).toBeTruthy();

    const fileUrl = "/api/v1/downloads/AAAAAAAAAAAAAAAAAAAAAA/file";
    FakeEventSource.last?.emit(job({ phase: "ready", version: 4, file_url: fileUrl }));
    expect(await screen.findByRole("link", { name: "Guardar archivo" })).toBeTruthy();
    expect(assign).toHaveBeenCalledWith(fileUrl);
    expect(FakeEventSource.last?.closed).toBe(true);
  });

  it("reports a failed job with its reason", async () => {
    mockFetch({
      "POST /api/v1/inspect": () => ({ status: 200, json: inspectOk }),
      "POST /api/v1/downloads": () => ({ status: 202, json: job() }),
    });
    render(Downloader);
    await analyze();
    await fireEvent.click(await screen.findByRole("button", { name: "Descargar" }));
    await waitFor(() => expect(FakeEventSource.last).not.toBeNull());
    FakeEventSource.last?.emit(
      job({ phase: "failed", version: 2, error_code: "TOO_LARGE", error_retryable: false }),
    );
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("demasiado grande");
    expect(screen.queryByRole("button", { name: "Intentar de nuevo" })).toBeNull();
    expect(screen.getByRole("button", { name: "Descargar" })).toBeTruthy();
  });
});
