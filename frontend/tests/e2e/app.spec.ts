import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const URL_IN = "https://www.youtube.com/watch?v=abc123";

const errors = new WeakMap<object, string[]>();

// Fail on CSP violations and uncaught exceptions. Browser "Failed to load resource" notes
// are expected for intentional API error responses and blocked external thumbnails.
test.beforeEach(async ({ page }) => {
  const seen: string[] = [];
  errors.set(page, seen);
  page.on("console", (msg) => {
    if (msg.type() === "error" && !msg.text().startsWith("Failed to load resource")) {
      seen.push(msg.text());
    }
  });
  page.on("pageerror", (err) => seen.push(err.message));
});

test.afterEach(async ({ page }) => {
  expect(errors.get(page)).toEqual([]);
});

test("landing is immediately usable and accessible", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Pega el enlace del vídeo que quieres descargar",
  );
  await expect(page.getByLabel("Enlace del vídeo", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Analizar" })).toBeEnabled();
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag22aa"])
    .analyze();
  expect(results.violations).toEqual([]);
  // No horizontal overflow at this viewport.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
});

test("paste → analyze → choose → download → file", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Enlace del vídeo", { exact: true }).fill(URL_IN);
  await page.getByRole("button", { name: "Analizar" }).click();

  const title = page.locator("#result-title");
  await expect(title).toHaveText("Sample <b>title</b>");
  await expect(title).toBeFocused();
  await expect(page.getByRole("radio", { name: /1080p/ })).toBeChecked();
  await page.getByRole("radio", { name: /720p/ }).check();

  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag22aa"]).analyze();
  expect(axe.violations).toEqual([]);

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Descargar" }).click();
  await expect(page.getByRole("progressbar")).toBeVisible();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("Sample b title b.mp4");
  await expect(page.getByRole("link", { name: "Guardar archivo" })).toBeVisible();
});

test("platform errors are explained", async ({ page }) => {
  await page.goto("/");
  await page
    .getByLabel("Enlace del vídeo", { exact: true })
    .fill("https://www.youtube.com/watch?v=private");
  await page.getByRole("button", { name: "Analizar" }).click();
  await expect(page.getByRole("alert")).toContainText("El contenido es privado");
});

test("unsupported and internal addresses are rejected on the field", async ({ page }) => {
  await page.goto("/");
  const input = page.getByLabel("Enlace del vídeo", { exact: true });
  await input.fill("https://example.org/video");
  await page.getByRole("button", { name: "Analizar" }).click();
  await expect(page.getByText("Este sitio no es compatible")).toBeVisible();
  await expect(input).toHaveAttribute("aria-invalid", "true");
  await input.fill("http://169.254.169.254/latest/meta-data");
  await page.keyboard.press("Enter");
  await expect(page.getByText("Esta dirección no está permitida")).toBeVisible();
});

test("theme toggle persists without flashing", async ({ page }) => {
  await page.goto("/");
  const toggle = page.locator("#theme-toggle");
  await expect(toggle).toBeVisible();
  await toggle.click(); // system → light
  await toggle.click(); // light → dark
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("legal pages render", async ({ page }) => {
  for (const path of ["/terminos", "/privacidad", "/copyright", "/uso-aceptable"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  }
});
