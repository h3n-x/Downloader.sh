import {
  formatBitrate,
  formatBytes,
  formatDate,
  formatDuration,
  percent,
} from "../../src/lib/format";

describe("format", () => {
  it("formats bytes with decimal units", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1_500)).toBe("1,5 KB");
    expect(formatBytes(93_000_000)).toBe("93 MB");
    expect(formatBytes(2_340_000_000)).toBe("2,3 GB");
    expect(formatBytes(null)).toBeNull();
    expect(formatBytes(-1)).toBeNull();
    expect(formatBytes(Number.NaN)).toBeNull();
  });

  it("formats durations", () => {
    expect(formatDuration(5)).toBe("0:05");
    expect(formatDuration(212)).toBe("3:32");
    expect(formatDuration(3_725)).toBe("1:02:05");
    expect(formatDuration(undefined)).toBeNull();
  });

  it("never invents a percentage", () => {
    expect(percent(50, 200)).toBe(25);
    expect(percent(250, 200)).toBe(100);
    expect(percent(10, null)).toBeNull();
    expect(percent(10, 0)).toBeNull();
    expect(percent(undefined, 100)).toBeNull();
  });

  it("formats dates in UTC and bitrates", () => {
    expect(formatDate("2026-01-02")).toMatch(/2026/);
    expect(formatDate("not-a-date")).toBeNull();
    expect(formatBitrate(4_400)).toBe("4,4 Mb/s");
    expect(formatBitrate(128)).toBe("128 kb/s");
    expect(formatBitrate(0)).toBeNull();
  });
});
