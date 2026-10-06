<script lang="ts">
import { es as t } from "../i18n/es";
import type { InspectOut, MediaFormat, QualityOption } from "../lib/api";
import { formatBitrate, formatBytes, formatDate, formatDuration, isoDuration } from "../lib/format";

interface Props {
  data: InspectOut;
  selected: string;
  disabled?: boolean;
  headingId: string;
}
let { data, selected = $bindable(), disabled = false, headingId }: Props = $props();

const media = $derived(data.media);
let thumbFailed = $state(false);
const duration = $derived(formatDuration(media.duration));
const published = $derived(formatDate(media.upload_date));
const firstVideo = $derived(data.options.find((o) => o.kind === "video")?.id);

function sizeText(o: QualityOption): string {
  const size = formatBytes(o.estimated_size);
  if (!size) return t.result.unknownSize;
  return o.size_is_estimate ? `${t.result.approx} ${size}` : size;
}

function optionTitle(o: QualityOption): string {
  return o.kind === "audio" ? t.result.audioOnly : o.label;
}

function resolution(f: MediaFormat): string {
  if (f.width && f.height) return `${f.width}×${f.height}`;
  return f.height ? `${f.height}p` : "—";
}

const formats = $derived(
  [...data.formats].sort(
    (a, b) =>
      Number(a.kind === "audio_only") - Number(b.kind === "audio_only") ||
      (b.height ?? 0) - (a.height ?? 0) ||
      (b.tbr ?? b.abr ?? 0) - (a.tbr ?? a.abr ?? 0),
  ),
);
</script>

<article class="card media" aria-labelledby={headingId}>
  <div class="thumb">
    {#if media.thumbnail && !thumbFailed}
      <!-- Decorative: the title conveys the content; external CDNs may be unreachable. -->
      <img
        src={media.thumbnail.url}
        alt=""
        onerror={() => (thumbFailed = true)}
        width={media.thumbnail.width ?? 480}
        height={media.thumbnail.height ?? 270}
        loading="lazy"
        decoding="async"
        referrerpolicy="no-referrer"
      />
    {/if}
  </div>

  <div class="info">
    <h2 id={headingId} class="title" tabindex="-1">{media.title}</h2>
    <p class="meta muted">
      <span class="provider">{media.provider.name}</span>
      {#if media.uploader}<span>{t.result.by} {media.uploader}</span>{/if}
      {#if duration && media.duration}
        <span><span class="visually-hidden">{t.result.duration}: </span><time datetime={isoDuration(media.duration)}>{duration}</time></span>
      {/if}
      {#if published}
        <span><span class="visually-hidden">{t.result.published}: </span><time datetime={media.upload_date}>{published}</time></span>
      {/if}
    </p>
  </div>

  <fieldset class="options" {disabled}>
    <legend>{t.result.quality}</legend>
    <div class="grid">
      {#each data.options as o (o.id)}
        <label class="option" class:is-disabled={o.exceeds_limit}>
          <input type="radio" name="quality" value={o.id} bind:group={selected} disabled={o.exceeds_limit} />
          <span class="option-main">
            <span class="option-title">{optionTitle(o)}</span>
            {#if o.id === firstVideo}<span class="badge">{t.result.best}</span>{/if}
            {#if o.is_default && o.id !== firstVideo}<span class="badge">{t.result.recommended}</span>{/if}
          </span>
          <span class="option-sub muted">
            {o.ext.toUpperCase()} · {o.exceeds_limit ? t.result.overLimit : sizeText(o)}
          </span>
        </label>
      {/each}
    </div>

    <details class="advanced">
      <summary>{t.result.advanced}</summary>
      <p class="muted small">{t.result.advancedHint}</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col"><span class="visually-hidden">{t.result.columns.pick}</span></th>
              <th scope="col">{t.result.columns.id}</th>
              <th scope="col">{t.result.columns.container}</th>
              <th scope="col">{t.result.columns.resolution}</th>
              <th scope="col">{t.result.columns.fps}</th>
              <th scope="col">{t.result.columns.vcodec}</th>
              <th scope="col">{t.result.columns.acodec}</th>
              <th scope="col">{t.result.columns.bitrate}</th>
              <th scope="col">{t.result.columns.size}</th>
            </tr>
          </thead>
          <tbody>
            {#each formats as f (f.format_id)}
              <tr>
                <td>
                  <input
                    type="radio"
                    name="quality"
                    value={`f:${f.format_id}`}
                    bind:group={selected}
                    aria-label={`${t.result.columns.id} ${f.format_id}`}
                  />
                </td>
                <td><code>{f.format_id}</code></td>
                <td>{f.ext}</td>
                <td>{f.kind === "audio_only" ? t.result.audioOnly : resolution(f)}</td>
                <td>{f.fps ? Math.round(f.fps) : "—"}</td>
                <td>{f.vcodec && f.vcodec !== "none" ? f.vcodec : "—"}</td>
                <td>{f.acodec && f.acodec !== "none" ? f.acodec : "—"}</td>
                <td>{formatBitrate(f.tbr ?? f.abr) ?? "—"}</td>
                <td>{formatBytes(f.filesize) ?? "—"}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </details>
  </fieldset>
</article>

<style>
  .media {
    display: grid;
    gap: var(--space-5);
    padding: var(--space-4);
  }
  @media (min-width: 40rem) {
    .media {
      grid-template-columns: minmax(0, 15rem) minmax(0, 1fr);
      padding: var(--space-5);
    }
    .options {
      grid-column: 1 / -1;
    }
  }
  .thumb {
    aspect-ratio: 16 / 9;
    border-radius: var(--radius);
    overflow: hidden;
    background: var(--surface-2);
  }
  .thumb img {
    width: 100%;
    height: 100%;
    object-fit: contain;
  }
  .info {
    display: grid;
    align-content: start;
    gap: var(--space-2);
    min-width: 0;
  }
  .title {
    font-size: var(--step-2);
    overflow-wrap: anywhere;
  }
  .title:focus {
    outline: none;
  }
  .meta {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-3);
    font-size: var(--step--1);
  }
  .provider {
    font-weight: var(--weight-medium);
    color: var(--text);
  }
  .options {
    border: 0;
    margin: 0;
    padding: 0;
    min-width: 0;
  }
  legend {
    font-weight: var(--weight-bold);
    margin-block-end: var(--space-3);
    padding: 0;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 9.5rem), 1fr));
    gap: var(--space-2);
  }
  .option {
    position: relative;
    display: grid;
    align-content: start;
    gap: var(--space-1);
    min-height: var(--target);
    padding: var(--space-3) var(--space-4);
    padding-inline-start: 2.75rem;
    border: var(--border-width) solid var(--border-strong);
    border-radius: var(--radius);
    background: var(--surface);
    cursor: pointer;
    transition:
      border-color var(--dur-fast) var(--ease),
      background-color var(--dur-fast) var(--ease);
  }
  .option:hover {
    background: var(--surface-2);
  }
  .option:has(input:checked) {
    border-color: var(--accent);
    background: var(--accent-soft);
    box-shadow: inset 0 0 0 1px var(--accent);
  }
  .option:has(input:focus-visible) {
    outline: 3px solid var(--focus);
    outline-offset: 2px;
  }
  .option input {
    position: absolute;
    inset-inline-start: var(--space-4);
    top: calc(var(--space-3) + 0.15rem);
    width: 1.125rem;
    height: 1.125rem;
    margin: 0;
    accent-color: var(--accent);
  }
  .option input:focus-visible {
    outline: none;
  }
  .option.is-disabled {
    cursor: not-allowed;
    opacity: 0.6;
  }
  .option-main {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
  .option-title {
    font-weight: var(--weight-bold);
    font-variant-numeric: tabular-nums;
  }
  .option-sub {
    font-size: var(--step--1);
  }
  .badge {
    font-size: 0.75rem;
    font-weight: var(--weight-medium);
    padding: 0.05rem 0.45rem;
    border-radius: 999px;
    border: var(--border-width) solid var(--accent);
    color: var(--accent);
  }
  .advanced {
    margin-block-start: var(--space-4);
  }
  summary {
    cursor: pointer;
    min-height: var(--target);
    display: flex;
    align-items: center;
    font-weight: var(--weight-medium);
    color: var(--accent);
  }
  .small {
    font-size: var(--step--1);
  }
  .table-wrap {
    overflow-x: auto;
    margin-block-start: var(--space-3);
    border: var(--border-width) solid var(--border);
    border-radius: var(--radius);
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--step--1);
    font-variant-numeric: tabular-nums;
  }
  th,
  td {
    text-align: start;
    padding: var(--space-2) var(--space-3);
    border-block-end: var(--border-width) solid var(--border);
    white-space: nowrap;
  }
  tbody tr:last-child td {
    border-block-end: 0;
  }
  th {
    background: var(--surface-2);
    font-weight: var(--weight-medium);
  }
  td input {
    width: 1.125rem;
    height: 1.125rem;
    accent-color: var(--accent);
  }
  code {
    font-family: var(--font-mono);
  }
</style>
