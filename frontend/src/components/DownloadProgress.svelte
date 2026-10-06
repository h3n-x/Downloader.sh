<script lang="ts">
import { onMount } from "svelte";
import { es as t } from "../i18n/es";
import type { JobOut } from "../lib/api";
import { formatBytes, formatDuration, formatTime, percent } from "../lib/format";

interface Props {
  job: JobOut;
  oncancel: () => void;
}
let { job, oncancel }: Props = $props();
let panel: HTMLElement | undefined = $state();

onMount(() => {
  const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  panel?.scrollIntoView({ block: "nearest", behavior: smooth ? "smooth" : "auto" });
});

const pct = $derived(percent(job.progress?.downloaded, job.progress?.total));
const label = $derived(
  job.phase === "downloading" && pct !== null
    ? `${t.progress.downloading} ${pct} %`
    : (t.progress[job.phase as keyof typeof t.progress] ?? t.progress.preparing),
);
const detail = $derived.by(() => {
  const p = job.progress;
  if (job.phase !== "downloading" || !p) return null;
  const parts: string[] = [];
  const done = formatBytes(p.downloaded);
  const total = formatBytes(p.total);
  if (done) parts.push(total ? `${done} ${t.progress.of} ${total}` : done);
  const speed = formatBytes(p.speed);
  if (speed) parts.push(`${speed}/s`);
  const eta = formatDuration(p.eta);
  if (eta && pct !== null) parts.push(`${eta} ${t.progress.left}`);
  return parts.join(" · ");
});
const ready = $derived(job.phase === "ready" && job.file_url);
const expires = $derived(formatTime(job.expires_at));
</script>

<section class="card progress" aria-labelledby="progress-title" bind:this={panel}>
  <h3 id="progress-title" class="status">{ready ? t.progress.ready : label}</h3>

  {#if ready}
    <p class="muted">{t.progress.readyHint}</p>
    <div class="actions">
      <a class="btn btn-primary" href={job.file_url} download>{t.progress.save}</a>
      {#if expires}
        <p class="muted small">{t.progress.expires} <time datetime={job.expires_at}>{expires}</time></p>
      {/if}
    </div>
  {:else}
    {#if pct !== null}
      <progress max="100" value={pct} aria-labelledby="progress-title"></progress>
    {:else}
      <progress aria-labelledby="progress-title"></progress>
    {/if}
    <p class="muted small detail">{detail ?? " "}</p>
    <div class="actions">
      <button type="button" class="btn btn-secondary" onclick={oncancel}>{t.progress.cancel}</button>
    </div>
  {/if}
</section>

<style>
  .progress {
    padding: var(--space-5);
    display: grid;
    gap: var(--space-3);
  }
  .status {
    font-size: var(--step-1);
    font-variant-numeric: tabular-nums;
  }
  progress {
    width: 100%;
    height: 0.75rem;
    accent-color: var(--accent);
  }
  /* Determinate bars use the palette; indeterminate keeps the native animation. */
  progress[value] {
    appearance: none;
    border: 0;
    border-radius: 999px;
    overflow: hidden;
    background: var(--surface-2);
    box-shadow: inset 0 0 0 1px var(--border);
  }
  progress[value]::-webkit-progress-bar {
    background: var(--surface-2);
  }
  progress[value]::-webkit-progress-value {
    background: var(--accent);
    transition: width var(--dur) var(--ease);
  }
  progress[value]::-moz-progress-bar {
    background: var(--accent);
  }
  .detail {
    font-variant-numeric: tabular-nums;
    min-height: 1.5em; /* reserved: no layout shift when details appear */
  }
  .small {
    font-size: var(--step--1);
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3) var(--space-4);
  }
</style>
