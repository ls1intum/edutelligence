/**
 * True when a click landed on (or inside) an element that handles its own
 * interaction, used by expandable table rows to ignore clicks on buttons,
 * links and inputs so only "plain" row clicks toggle expansion.
 */
export function isInteractiveClick(event: Event): boolean {
  const target = event.target as HTMLElement | null;
  return target?.closest('button, a, input, select, textarea, label') != null;
}
