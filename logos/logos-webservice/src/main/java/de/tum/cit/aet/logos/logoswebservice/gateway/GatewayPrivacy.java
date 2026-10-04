package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.List;

/**
 * Privacy gate for the direct-cloud path — mirrors
 * {@code pipeline._privacy_ok} / {@code PRIVACY_ORDER} in the orchestrator.
 *
 * <p>Order is the Postgres / orchestrator trust axis (most trusted first),
 * not Java enum declaration order.
 */
final class GatewayPrivacy {

    /**
     * Most trusted → least trusted. Keep in sync with
     * {@code ThresholdLevel} in {@code logos-orchestrator/.../dbmodules.py}.
     */
    static final List<String> PRIVACY_ORDER = List.of(
        "LOCAL",
        "CLOUD_IN_EU_BY_EU_PROVIDER",
        "CLOUD_IN_EU_BY_US_PROVIDER",
        "CLOUD_NOT_IN_EU_BY_US_PROVIDER",
        "THIRD_PARTY_HARDWARE"
    );

    /** Default when the client does not set a policy (orchestrator default). */
    static final String DEFAULT_THRESHOLD = "CLOUD_NOT_IN_EU_BY_US_PROVIDER";

    private GatewayPrivacy() {
    }

    /**
     * Whether a deployment with privacy {@code level} satisfies a request
     * whose policy demands {@code threshold}.
     */
    static boolean privacyOk(String threshold, String level) {
        String t = threshold == null || threshold.isBlank() ? DEFAULT_THRESHOLD : threshold.strip();
        String l = level == null || level.isBlank() ? "LOCAL" : level.strip();
        int thresholdIdx = PRIVACY_ORDER.indexOf(t);
        if (thresholdIdx < 0) {
            thresholdIdx = 0; // fail closed → strictest
        }
        int levelIdx = PRIVACY_ORDER.indexOf(l);
        if (levelIdx < 0) {
            levelIdx = PRIVACY_ORDER.size() - 1; // fail closed → least trusted
        }
        return thresholdIdx >= levelIdx;
    }
}
