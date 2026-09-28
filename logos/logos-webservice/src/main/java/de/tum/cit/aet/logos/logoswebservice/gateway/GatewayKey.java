package de.tum.cit.aet.logos.logoswebservice.gateway;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;

/**
 * Active Logos API key fields the inference gateway needs (no JPA entity).
 *
 * <p>{@code logLevel} is the key's configured request-logging level
 * ({@code BILLING} or {@code FULL}), which decides whether a request's payloads
 * are stored alongside its billing row.
 */
public record GatewayKey(
        int id,
        String keyValue,
        String name,
        ApiKeyType keyType,
        Integer teamId,
        Integer userId,
        String environment,
        boolean useCustomPermissions,
        String settingsJson,
        int defaultPriority,
        String logLevel) {

    /** Whether this key's requests are logged with their payloads. */
    public boolean logsFullPayloads() {
        return "FULL".equalsIgnoreCase(logLevel);
    }
}
