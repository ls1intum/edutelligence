/**
 * Service-level agreements for an application key's queued traffic.
 *
 * An SLA is a presentation of `api_keys.default_priority`, the per-key queue
 * priority the orchestrator resolves in `pipeline.resolve_queue_priority` — a
 * field of its own, separate from the Logos-admin-set `teams.priority`. There
 * are exactly three tiers, and they carry the values the orchestrator's
 * `Priority` enum maps to its queue buckets.
 */
export type KeySla = 'ux-critical' | 'ux-high-prio' | 'ux-background';

/** The `default_priority` written for each tier. */
export const SLA_PRIORITY: Record<KeySla, number> = {
  'ux-critical': 10,
  'ux-high-prio': 5,
  'ux-background': 1,
};

/** The tier a key gets when nobody has chosen one. */
export const DEFAULT_SLA: KeySla = 'ux-high-prio';

export interface SlaOption {
  value: KeySla;
  label: string;
  /** What the tier promises, shown as the select's tooltip. */
  hint: string;
}

export const SLA_OPTIONS: readonly SlaOption[] = [
  {
    value: 'ux-critical',
    label: 'ux-critical',
    hint: 'A user is waiting — the model is kept warm and the request is always served.',
  },
  {
    value: 'ux-high-prio',
    label: 'ux-high-prio',
    hint: 'Asynchronous work — minutes are fine, but it should not wait on idle capacity.',
  },
  {
    value: 'ux-background',
    label: 'ux-background',
    hint: 'Overnight work — runs whenever there are idle GPUs to fill.',
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
  if (priority === SLA_PRIORITY['ux-critical']) return 'ux-critical';
  if (priority === SLA_PRIORITY['ux-background']) return 'ux-background';
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
