// Post-build: hash every inline <script>/<style> Astro emitted (island runtime) so the
// backend can allow exactly those blocks in its CSP instead of 'unsafe-inline'.
import { createHash } from "node:crypto";
import { readdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

const dist = new URL("../dist/", import.meta.url).pathname;
const hash = (body) => `'sha256-${createHash("sha256").update(body, "utf8").digest("base64")}'`;

async function* htmlFiles(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) yield* htmlFiles(path);
    else if (entry.name.endsWith(".html")) yield path;
  }
}

const scripts = new Set();
const styles = new Set();
for await (const file of htmlFiles(dist)) {
  const html = await readFile(file, "utf8");
  for (const [, attrs, body] of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)) {
    if (/\bsrc=/.test(attrs) || /type="application\/ld\+json"/.test(attrs) || !body) continue;
    scripts.add(hash(body));
  }
  for (const [, body] of html.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/g))
    styles.add(hash(body));
  if (/\sstyle="/.test(html)) throw new Error(`inline style attribute in ${file} (blocked by CSP)`);
}
const out = { script: [...scripts].sort(), style: [...styles].sort() };
await writeFile(join(dist, "csp-hashes.json"), `${JSON.stringify(out, null, 2)}\n`);
console.log(`csp-hashes: ${out.script.length} script(s), ${out.style.length} style(s)`);
