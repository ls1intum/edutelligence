package de.tum.cit.aet.logos.logoswebservice.gateway;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;

/** Active Logos API key fields the inference gateway needs (no JPA entity). */
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
        int defaultPriority) {
}
