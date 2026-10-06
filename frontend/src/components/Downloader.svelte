<script lang="ts">
import { onDestroy, onMount, tick } from "svelte";
import { es as t } from "../i18n/es";
import {
  ApiError,
  cancelDownload,
  createDownload,
  type ErrorCode,
  type InspectOut,
  inspect,
  type JobOut,
  watchDownload,
} from "../lib/api";
import DownloadProgress from "./DownloadProgress.svelte";
import ErrorNotice from "./ErrorNotice.svelte";
import MediaResult from "./MediaResult.svelte";

type Stage = "idle" | "inspecting" | "inspected" | "downloading" | "ready";
type Failure = { code: ErrorCode | "NETWORK"; retryable: boolean; retry: () => void };

/** Errors that concern the URL itself are shown on the field, not as a banner. */
const FIELD_ERRORS: ReadonlySet<string> = new Set([
  "INVALID_URL",
  "URL_NOT_ALLOWED",
  "UNSUPPORTED_SITE",
  "UNSUPPORTED_CONTENT",
  "VALIDATION_ERROR",
]);

let url = $state("");
let stage: Stage = $state("idle");
let result: InspectOut | null = $state(null);
let inspectedUrl = "";
let selected = $state("");
let job: JobOut | null = $state(null);
let failure: Failure | null = $state(null);
let fieldError: string | null = $state(null);
let announcement = $state("");
let canPaste = $state(false);

let input: HTMLInputElement | undefined = $state();
let controller: AbortController | null = null;
let stopWatching: (() => void) | null = null;
let lastPhase = "";

const busy = $derived(stage === "inspecting" || stage === "downloading");

onMount(() => {
  canPaste = typeof navigator.clipboard?.readText === "function";
  const shared = new URLSearchParams(location.search).get("url");
  if (shared) url = shared.slice(0, 4096);
});

onDestroy(() => {
  controller?.abort();
  stopWatching?.();
});

function fail(error: unknown, retry: () => void): void {
  if (error instanceof DOMException && error.name === "AbortError") return;
  const e = error instanceof ApiError ? error : new ApiError("INTERNAL_ERROR", true);
  if (FIELD_ERRORS.has(e.code)) {
    fieldError = e.code;
    input?.focus();
  } else {
    failure = { code: e.code, retryable: e.retryable, retry };
  }
}

async function analyze(event?: SubmitEvent): Promise<void> {
  event?.preventDefault();
  const value = url.trim();
  failure = null;
  fieldError = null;
  if (!value) {
    fieldError = "EMPTY";
    input?.focus();
    return;
  }
  controller?.abort();
  controller = new AbortController();
  stopWatching?.();
  job = null;
  result = null;
  stage = "inspecting";
  announcement = t.form.submitting;
  try {
    const data = await inspect(value, controller.signal);
    result = data;
    inspectedUrl = value;
    selected = data.options.find((o) => o.is_default)?.id ?? data.options[0]?.id ?? "";
    stage = "inspected";
    announcement = data.media.title;
    await tick();
    document.getElementById("result-title")?.focus();
  } catch (e) {
    stage = "idle";
    announcement = "";
    fail(e, () => void analyze());
  }
}

async function paste(): Promise<void> {
  try {
    const text = (await navigator.clipboard.readText()).trim();
    if (text) {
      url = text.slice(0, 4096);
      await analyze();
    }
  } catch {
    input?.focus(); // permission denied: let the user paste manually
  }
}

async function download(): Promise<void> {
  if (!result || !selected) return;
  failure = null;
  stage = "downloading";
  lastPhase = "";
  try {
    job = await createDownload(inspectedUrl, selected);
  } catch (e) {
    stage = "inspected";
    fail(e, () => void download());
    return;
  }
  stopWatching = watchDownload(job, onJob, (e) => {
    stage = "inspected";
    fail(e, () => void download());
  });
}

function onJob(next: JobOut): void {
  job = next;
  if (next.phase !== lastPhase) {
    lastPhase = next.phase;
    announcement = t.progress[next.phase as keyof typeof t.progress] ?? "";
  }
  if (next.phase === "ready" && next.file_url) {
    stage = "ready";
    window.location.assign(next.file_url);
  } else if (next.phase === "failed" || next.phase === "expired") {
    stage = "inspected";
    const code = next.error_code ?? "INTERNAL_ERROR";
    failure = {
      code,
      retryable: next.error_retryable ?? true,
      retry: () => void download(),
    };
  } else if (next.phase === "cancelled") {
    stage = "inspected";
  }
}

async function cancel(): Promise<void> {
  const current = job;
  stopWatching?.();
  stage = "inspected";
  job = null;
  announcement = t.progress.cancelled;
  if (current) await cancelDownload(current.id).catch(() => undefined);
}

async function reset(): Promise<void> {
  controller?.abort();
  stopWatching?.();
  url = "";
  result = null;
  job = null;
  failure = null;
  fieldError = null;
  stage = "idle";
  await tick();
  input?.focus();
}

const fieldMessage = $derived(
  fieldError === "EMPTY"
    ? { title: t.form.empty, hint: "" }
    : fieldError
      ? t.errors.codes[fieldError as ErrorCode]
      : null,
);
</script>

<div class="downloader">
  <form class="url-form" onsubmit={analyze} novalidate>
    <label for="url" class="label">{t.form.label}</label>
    <div class="row">
      <input
        bind:this={input}
        bind:value={url}
        id="url"
        name="url"
        type="url"
        inputmode="url"
        autocomplete="off"
        autocapitalize="off"
        spellcheck="false"
        enterkeyhint="go"
        maxlength="4096"
        placeholder={t.form.placeholder}
        aria-invalid={fieldError ? "true" : undefined}
        aria-describedby={fieldError ? "url-error" : undefined}
        disabled={stage === "downloading"}
      />
      <div class="buttons">
        {#if canPaste}
          <button type="button" class="btn btn-secondary" onclick={paste} disabled={busy}>{t.form.paste}</button>
        {/if}
        <button type="submit" class="btn btn-primary" disabled={busy} aria-busy={stage === "inspecting"}>
          {stage === "inspecting" ? t.form.submitting : t.form.submit}
        </button>
      </div>
    </div>
    {#if fieldMessage}
      <p id="url-error" class="field-error">
        <strong>{fieldMessage.title}</strong>
        {#if fieldMessage.hint}<span>{fieldMessage.hint}</span>{/if}
      </p>
    {/if}
  </form>

  <p class="visually-hidden" aria-live="polite" aria-atomic="true">{announcement}</p>

  {#if stage === "inspecting"}
    <div class="card skeleton" aria-hidden="true">
      <div class="sk-thumb"></div>
      <div class="sk-lines"><div></div><div></div><div></div></div>
    </div>
  {/if}

  {#if failure}
    <ErrorNotice code={failure.code} retryable={failure.retryable} onretry={failure.retry} />
  {/if}

  {#if result}
    <MediaResult data={result} bind:selected disabled={stage === "downloading"} headingId="result-title" />

    {#if job && (stage === "downloading" || stage === "ready")}
      <DownloadProgress {job} oncancel={cancel} />
    {/if}

    <div class="result-actions">
      {#if stage === "inspected"}
        <button type="button" class="btn btn-primary" onclick={download} disabled={!selected}>
          {t.result.download}
        </button>
      {/if}
      <button type="button" class="btn btn-secondary" onclick={reset}>{t.result.another}</button>
    </div>
  {/if}
</div>

<style>
  .downloader {
    display: grid;
    gap: var(--space-5);
  }
  .url-form {
    display: grid;
    gap: var(--space-2);
  }
  .label {
    font-weight: var(--weight-medium);
  }
  .row {
    display: grid;
    gap: var(--space-2);
  }
  @media (min-width: 40rem) {
    .row {
      grid-template-columns: minmax(0, 1fr) auto;
    }
  }
  input {
    width: 100%;
    min-height: 3.25rem;
    padding: 0 var(--space-4);
    border: 2px solid var(--border-strong);
    border-radius: var(--radius);
    background: var(--surface);
    font-family: var(--font-mono);
    font-size: max(1rem, var(--step-0)); /* ≥16px: no iOS zoom on focus */
    transition: border-color var(--dur-fast) var(--ease);
  }
  input:focus-visible {
    border-color: var(--focus);
    outline-offset: 1px;
  }
  input[aria-invalid="true"] {
    border-color: var(--danger);
  }
  .buttons {
    display: flex;
    gap: var(--space-2);
  }
  .buttons .btn {
    flex: 1;
    min-height: 3.25rem;
  }
  .field-error {
    display: grid;
    gap: var(--space-1);
    color: var(--danger);
    font-size: var(--step--1);
  }
  .field-error span {
    color: var(--text);
  }
  .result-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3);
  }
  @media (max-width: 39.99rem) {
    .result-actions .btn {
      flex: 1 1 100%;
    }
  }
  .skeleton {
    display: grid;
    gap: var(--space-4);
    padding: var(--space-4);
  }
  @media (min-width: 40rem) {
    .skeleton {
      grid-template-columns: 15rem 1fr;
      padding: var(--space-5);
    }
  }
  .sk-thumb {
    aspect-ratio: 16 / 9;
    border-radius: var(--radius);
  }
  .sk-lines {
    display: grid;
    gap: var(--space-3);
    align-content: start;
  }
  .sk-lines div {
    height: 1rem;
    border-radius: var(--radius-sm);
  }
  .sk-lines div:first-child {
    height: 1.5rem;
    width: 85%;
  }
  .sk-lines div:last-child {
    width: 45%;
  }
  .sk-thumb,
  .sk-lines div {
    background: var(--surface-2);
    animation: pulse 1.4s var(--ease) infinite;
  }
  @keyframes pulse {
    50% {
      opacity: 0.55;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .sk-thumb,
    .sk-lines div {
      animation: none;
    }
  }
</style>
