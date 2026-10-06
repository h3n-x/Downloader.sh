/** Typed API client generated from the backend's OpenAPI contract. */
import createClient from "openapi-fetch";
import type { components, paths } from "./api-types";

export type InspectOut = components["schemas"]["InspectOut"];
export type QualityOption = components["schemas"]["QualityOption"];
export type MediaFormat = components["schemas"]["MediaFormat"];
export type JobOut = components["schemas"]["JobOut"];
export type ErrorCode = components["schemas"]["ErrorCode"];
export type Phase = components["schemas"]["Phase"];

/** A failure the UI can explain: an API error code or a network failure. */
export class ApiError extends Error {
  constructor(
    readonly code: ErrorCode | "NETWORK",
    readonly retryable: boolean,
    readonly retryAfter?: number,
  ) {
    super(code);
    this.name = "ApiError";
  }
}

// Resolve fetch lazily so instrumentation/test doubles installed later are honoured.
const client = createClient<paths>({ baseUrl: "", fetch: (request) => globalThis.fetch(request) });

type ErrorPayload = { error?: { code?: ErrorCode; retryable?: boolean; retry_after?: number } };

function toApiError(payload: unknown, status: number): ApiError {
  const err = (payload as ErrorPayload | undefined)?.error;
  if (err?.code) return new ApiError(err.code, Boolean(err.retryable), err.retry_after);
  return new ApiError(status >= 500 ? "INTERNAL_ERROR" : "VALIDATION_ERROR", status >= 500);
}

async function call<T>(
  run: () => Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: Awaited<ReturnType<typeof run>>;
  try {
    result = await run();
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError("NETWORK", true);
  }
  if (result.data !== undefined) return result.data;
  throw toApiError(result.error, result.response.status);
}

export function inspect(url: string, signal?: AbortSignal): Promise<InspectOut> {
  return call(() => client.POST("/api/v1/inspect", { body: { url }, signal: signal ?? null }));
}

export function createDownload(url: string, optionId: string): Promise<JobOut> {
  return call(() => client.POST("/api/v1/downloads", { body: { url, option_id: optionId } }));
}

export function getDownload(id: string): Promise<JobOut> {
  return call(() => client.GET("/api/v1/downloads/{job_id}", { params: { path: { job_id: id } } }));
}

export async function cancelDownload(id: string): Promise<void> {
  await client.DELETE("/api/v1/downloads/{job_id}", { params: { path: { job_id: id } } });
}

const TERMINAL: ReadonlySet<Phase> = new Set(["ready", "failed", "cancelled", "expired"]);

export function isTerminal(phase: Phase): boolean {
  return TERMINAL.has(phase);
}

/**
 * Follow a job via Server-Sent Events, falling back to polling if SSE is unavailable
 * (some proxies buffer event streams). Returns a function that stops watching.
 */
export function watchDownload(
  job: JobOut,
  onUpdate: (job: JobOut) => void,
  onError: (error: ApiError) => void,
): () => void {
  let stopped = false;
  let source: EventSource | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const stop = () => {
    stopped = true;
    source?.close();
    if (timer) clearTimeout(timer);
  };

  const handle = (next: JobOut) => {
    if (stopped) return;
    onUpdate(next);
    if (isTerminal(next.phase)) stop();
  };

  const poll = async () => {
    if (stopped) return;
    try {
      handle(await getDownload(job.id));
    } catch (e) {
      if (e instanceof ApiError && !e.retryable) {
        stop();
        onError(e);
        return;
      }
    }
    if (!stopped) timer = setTimeout(poll, 1000);
  };

  if (typeof EventSource === "undefined") {
    void poll();
    return stop;
  }
  source = new EventSource(job.events_url);
  source.addEventListener("job", (event) => {
    handle(JSON.parse((event as MessageEvent<string>).data) as JobOut);
  });
  source.onerror = () => {
    // The stream ends normally after a terminal event; otherwise degrade to polling.
    source?.close();
    if (!stopped) void poll();
  };
  return stop;
}
