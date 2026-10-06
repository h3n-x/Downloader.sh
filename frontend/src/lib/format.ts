/** Locale-aware formatting helpers (pure, unit-tested). */

const UNITS = ["B", "KB", "MB", "GB", "TB"] as const;

export function formatBytes(bytes: number | null | undefined, locale = "es"): string | null {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return null;
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < UNITS.length - 1) {
    value /= 1000;
    unit += 1;
  }
  const digits = unit === 0 || value >= 100 ? 0 : 1;
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(value)} ${UNITS[unit]}`;
}

export function formatDuration(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return null;
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = h > 0 ? String(m).padStart(2, "0") : String(m);
  return `${h > 0 ? `${h}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
}

/** ISO 8601 duration for <time datetime>. */
export function isoDuration(seconds: number): string {
  return `PT${Math.round(seconds)}S`;
}

export function formatDate(iso: string | null | undefined, locale = "es"): string | null {
  if (!iso) return null;
  const date = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone: "UTC" }).format(date);
}

export function formatTime(iso: string | null | undefined, locale = "es"): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(locale, { timeStyle: "short" }).format(date);
}

/** Percentage only when the total is known; `null` means "indeterminate". */
export function percent(downloaded?: number | null, total?: number | null): number | null {
  if (downloaded == null || total == null || total <= 0) return null;
  return Math.min(100, Math.max(0, Math.floor((downloaded / total) * 100)));
}

export function formatBitrate(kbps: number | null | undefined, locale = "es"): string | null {
  if (kbps == null || !Number.isFinite(kbps) || kbps <= 0) return null;
  if (kbps >= 1000) {
    return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(kbps / 1000)} Mb/s`;
  }
  return `${Math.round(kbps)} kb/s`;
}
