<script lang="ts">
import { es as t } from "../i18n/es";
import type { ErrorCode } from "../lib/api";

interface Props {
  code: ErrorCode | "NETWORK";
  retryable?: boolean;
  onretry?: () => void;
}
let { code, retryable = false, onretry }: Props = $props();

const text = $derived(code === "NETWORK" ? t.errors.network : t.errors.codes[code]);
</script>

<div class="notice" role="alert">
  <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <path d="M12 3 2 21h20L12 3Zm0 6v5m0 3v.01" />
  </svg>
  <div class="body">
    <p class="title">{text.title}</p>
    <p class="hint">{text.hint}</p>
    {#if retryable && onretry}
      <button type="button" class="btn btn-secondary retry" onclick={onretry}>{t.errors.retry}</button>
    {/if}
  </div>
</div>

<style>
  .notice {
    display: flex;
    gap: var(--space-3);
    padding: var(--space-4);
    border: var(--border-width) solid var(--danger);
    border-inline-start-width: 4px;
    border-radius: var(--radius);
    background: var(--danger-soft);
  }
  .icon {
    flex: none;
    width: 1.5rem;
    height: 1.5rem;
    fill: none;
    stroke: var(--danger);
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .title {
    font-weight: var(--weight-bold);
  }
  .hint {
    color: var(--text);
    margin-block-start: var(--space-1);
  }
  .retry {
    margin-block-start: var(--space-3);
  }
</style>
