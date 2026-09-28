/**
 * Service-level agreements for an application key's queued traffic.
 *
 * An SLA is a presentation of `api_keys.default_priority`, the per-key queue
 * priority the orchestrator resolves in `pipeline.resolve_queue_priority`:
 * a non-zero key priority wins over the team's admin-set priority, which wins
 * over the policy-level one. The three tiers are the values the orchestrator's
 * `Priority` enum maps to its own queue buckets — every other value falls back
 * to the NORMAL bucket, so it is surfaced as `medium` here rather than being
 * silently rewritten.
 */
export type KeySla = 'high' | 'medium' | 'low' | 'inherit';

/** The `default_priority` written for each tier. 0 = "not set" (inherit). */
export const SLA_PRIORITY: Record<KeySla, number> = {
  high: 10,
  medium: 5,
  low: 1,
  inherit: 0,
};

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
  {
    value: 'inherit',
    label: 'Team Default',
    hint: "No priority set on the key: the team's queue priority applies, then the policy's.",
  },
] as const;

/** Tier of a stored `default_priority`, mirroring the orchestrator's bucketing. */
export function slaOfPriority(priority: number | null | undefined): KeySla {
  if (priority == null || priority === 0) return 'inherit';
  if (priority === SLA_PRIORITY.high) return 'high';
  if (priority === SLA_PRIORITY.low) return 'low';
  return 'medium';
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
