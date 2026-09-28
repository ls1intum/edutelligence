/**
 * Service-level agreements for an application key's queued traffic.
 *
 * An SLA is a presentation of `api_keys.default_priority`, the per-key queue
 * priority the orchestrator resolves in `pipeline.resolve_queue_priority` — a
 * field of its own, separate from the Logos-admin-set `teams.priority`. There
 * are exactly three tiers, and they carry the values the orchestrator's
 * `Priority` enum maps to its queue buckets.
 */
export type KeySla = 'high' | 'medium' | 'low';

/** The `default_priority` written for each tier. */
export const SLA_PRIORITY: Record<KeySla, number> = {
  high: 10,
  medium: 5,
  low: 1,
};

/** The tier a key gets when nobody has chosen one. */
export const DEFAULT_SLA: KeySla = 'medium';

export interface SlaOption {
  value: KeySla;
  label: string;
  /** What the tier promises, shown as the select's tooltip. */
  hint: string;
}

export const SLA_OPTIONS: readonly SlaOption[] = [
  {
    value: 'high',
    label: 'High Priority',
    hint: 'Requests on this key are always served, ahead of every other tier.',
  },
  {
    value: 'medium',
    label: 'Medium Priority',
    hint: 'Requests are served normally, but queue behind high-priority traffic while that is pending.',
  },
  {
    value: 'low',
    label: 'Low Priority',
    hint: 'Requests are served whenever there is spare capacity; a delay of hours is acceptable.',
  },
] as const;

/**
 * Tier of a stored `default_priority`.
 *
 * Only 10 and 1 name a tier of their own. Everything else reads as the default
 * tier, which matches what the queue does with those values: the orchestrator's
 * `Priority.from_int` recognises 1, 5 and 10 and buckets every other number as
 * NORMAL, and a key left at 0 resolves to the team's or the policy's priority,
 * which is NORMAL unless an admin set something else.
 */
export function slaOfPriority(priority: number | null | undefined): KeySla {
  if (priority === SLA_PRIORITY.high) return 'high';
  if (priority === SLA_PRIORITY.low) return 'low';
  return DEFAULT_SLA;
}

/** Sort rank of a tier — lower sorts first, so the strictest SLA is on top. */
export function slaRank(sla: KeySla): number {
  return SLA_OPTIONS.findIndex((o) => o.value === sla);
}

export function slaLabel(sla: KeySla): string {
  return SLA_OPTIONS.find((o) => o.value === sla)?.label ?? sla;
}

export function slaHint(sla: KeySla): string {
  return SLA_OPTIONS.find((o) => o.value === sla)?.hint ?? '';
}
