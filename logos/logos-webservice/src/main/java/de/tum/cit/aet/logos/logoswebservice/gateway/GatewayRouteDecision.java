package de.tum.cit.aet.logos.logoswebservice.gateway;

/**
 * Result of {@link GatewayRouteResolver#resolve}.
 *
 * @param route       CLOUD or ORCHESTRATOR
 * @param deployment  the cloud deployment to forward to when {@code route == CLOUD}; otherwise null
 * @param reason      short explanation (for logs / tests)
 */
public record GatewayRouteDecision(
        GatewayRoute route,
        GatewayDeployment deployment,
        String reason
) {
    public static GatewayRouteDecision orchestrator(String reason) {
        return new GatewayRouteDecision(GatewayRoute.ORCHESTRATOR, null, reason);
    }

    public static GatewayRouteDecision cloud(GatewayDeployment deployment, String reason) {
        return new GatewayRouteDecision(GatewayRoute.CLOUD, deployment, reason);
    }
}
