package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.List;

/**
 * Authenticated gateway call: the active API key plus, when a named model was
 * resolved in the same round-trip, its permitted deployments.
 */
public record GatewayAuthContext(GatewayKey key, List<GatewayDeployment> deploymentsForModel) {
}
