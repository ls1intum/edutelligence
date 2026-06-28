/** Map a mouse event to a 0..1 fraction across the chart's plot area, or null. SSR-safe (called only from client handlers). */
export function pointerPlotFrac(
  event: MouseEvent,
  svg: SVGSVGElement | null,
  viewW: number,
  padLeft: number,
  padRight: number,
): number | null {
  if (!svg) return null;
  const rect = svg.getBoundingClientRect();
  if (rect.width === 0) return null;
  const scaleX = viewW / rect.width;
  const vbX = (event.clientX - rect.left) * scaleX;
  const plotW = viewW - padLeft - padRight;
  if (plotW <= 0) return null;
  const frac = (vbX - padLeft) / plotW;
  return Math.max(0, Math.min(1, frac));
}

/** Nearest bucket index for a 0..1 fraction over n buckets. */
export function nearestIndex(frac: number, n: number): number {
  if (n <= 0) return 0;
  return Math.max(0, Math.min(n - 1, Math.round(frac * (n - 1))));
}
