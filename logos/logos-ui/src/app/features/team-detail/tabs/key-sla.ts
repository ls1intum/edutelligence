/**
 * Service-level agreements for an application key's queued traffic.
 *
 * An SLA is a presentation of `api_keys.default_priority`, the per-key queue
 * priority the orchestrator resolves in `pipeline.resolve_queue_priority` — a
 * field of its own, separate from the Logos-admin-set `teams.priority`. There
 * are exactly three tiers a key can promise, and they carry the values the
 * orchestrator's `Priority` enum maps to its queue buckets. A key left at 0
 * (unset) inherits the team's or the policy's priority and is shown as such
 * rather than as one of the three choices.
 */
export type KeySla = 'ux-critical' | 'ux-high-prio' | 'ux-background';

/** The `default_priority` written for each tier. */
export const SLA_PRIORITY: Record<KeySla, number> = {
  'ux-critical': 10,
  'ux-high-prio': 5,
  'ux-background': 1,
};

/** The tier a key gets when nobody has chosen one and nothing is inherited. */
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
    hint: 'A user is waiting — traffic enters the high-priority queue and is served ahead of lower tiers.',
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

/** Hint when a key has no priority of its own and follows the team/policy. */
export const INHERITED_SLA_HINT =
  "No per-key SLA — the team's or the policy's priority applies until an owner picks a tier.";

/** True when the key has no priority of its own (0 / null / unset). */
export function isUnsetPriority(priority: number | null | undefined): boolean {
  return priority == null || priority === 0;
}

/**
 * Tier of an *explicit* stored `default_priority` (not unset).
 *
 * Only 10 and 1 name a tier of their own. Everything else reads as the default
 * tier, which matches what the queue does: the orchestrator's `Priority.from_int`
 * recognises 1, 5 and 10 and buckets every other number as NORMAL.
 */
export function slaOfPriority(priority: number | null | undefined): KeySla {
  if (priority === SLA_PRIORITY['ux-critical']) return 'ux-critical';
  if (priority === SLA_PRIORITY['ux-background']) return 'ux-background';
  return DEFAULT_SLA;
}

/**
 * Effective display/sort tier, matching `resolve_queue_priority` then
 * `Priority.from_int`: an unset key follows the team's priority when set,
 * otherwise the default NORMAL tier.
 */
export function effectiveSla(
  keyPriority: number | null | undefined,
  teamPriority?: number | null,
): KeySla {
  if (!isUnsetPriority(keyPriority)) return slaOfPriority(keyPriority);
  if (teamPriority) return slaOfPriority(teamPriority);
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
