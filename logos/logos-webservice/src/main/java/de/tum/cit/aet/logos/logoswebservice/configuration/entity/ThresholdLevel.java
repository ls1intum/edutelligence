package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

/**
 * Privacy levels, mirroring the Postgres enum {@code threshold_enum} and the
 * orchestrator's {@code ThresholdLevel} in
 * {@code logos-orchestrator/src/logos/dbutils/dbmodules.py} (the single
 * ordered definition, most trusted first). Keep all three in sync.
 *
 * <p>{@code THIRD_PARTY_HARDWARE} covers hardware outside operator control —
 * e.g. a personal Mac running the MLX worker — whose owner can inspect the
 * running processes. It orders below every cloud tier, so {@code LOCAL}
 * keeps meaning "our datacentre" and such a machine is only ever eligible
 * for policies that explicitly allow it.
 */
public enum ThresholdLevel {
    LOCAL,
    CLOUD_IN_EU_BY_US_PROVIDER,
    CLOUD_NOT_IN_EU_BY_US_PROVIDER,
    CLOUD_IN_EU_BY_EU_PROVIDER,
    THIRD_PARTY_HARDWARE
}
