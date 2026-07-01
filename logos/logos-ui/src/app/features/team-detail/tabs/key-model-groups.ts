// Shared helper for the key-permissions expand row in the members and
// application-keys tabs. Both surfaces show, per key, which models are
// reachable and which provider(s) serve each one — mirroring the
// model-grouped view used on the My Workspace page.

export interface KeyModelGroup {
  model_name: string;
  providers: string[];
  hasCloud: boolean;
  hasLocal: boolean;
}

export interface ProviderInfo {
  id: number;
  name: string;
  isCloud: boolean;
}

/**
 * Build the model→provider groups for a key.
 *
 * A model is only reachable when the key is permitted both the model AND a
 * provider that actually serves it, so models without a serving accessible
 * provider are dropped (matching the resolved access shown on My Workspace).
 *
 * @param accessibleProviders providers permitted for this key
 * @param accessibleModels    models permitted for this key
 * @param providerModelMap    providerId → set of model ids that provider serves
 */
export function buildKeyModelGroups(
  accessibleProviders: ProviderInfo[],
  accessibleModels: { id: number; name: string }[],
  providerModelMap: Map<number, Set<number>>,
): KeyModelGroup[] {
  const groups: KeyModelGroup[] = [];
  for (const model of accessibleModels) {
    const serving = accessibleProviders.filter((p) =>
      providerModelMap.get(p.id)?.has(model.id),
    );
    if (serving.length === 0) continue;
    groups.push({
      model_name: model.name,
      providers: serving.map((p) => p.name).sort((a, b) => a.localeCompare(b)),
      hasCloud: serving.some((p) => p.isCloud),
      hasLocal: serving.some((p) => !p.isCloud),
    });
  }
  // Cloud-bearing models first, then local-only; alphabetical within each group.
  return groups.sort((a, b) => {
    if (a.hasCloud !== b.hasCloud) return a.hasCloud ? -1 : 1;
    return a.model_name.localeCompare(b.model_name);
  });
}
