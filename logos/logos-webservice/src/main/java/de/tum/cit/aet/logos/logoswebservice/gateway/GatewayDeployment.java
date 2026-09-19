package de.tum.cit.aet.logos.logoswebservice.gateway;

/**
 * One permitted model↔provider deployment row for gateway routing.
 *
 * <p>Fields mirror the orchestrator's {@code get_auth_info_to_deployment} /
 * {@code get_deployments_for_api_key} join (auth + routing columns needed to
 * forward to a cloud upstream without another query).
 */
public record GatewayDeployment(
        int modelId,
        String modelName,
        Integer providerId,
        String providerName,
        String providerType,
        String cloudProviderType,
        String baseUrl,
        String endpoint,
        String authName,
        String authFormat,
        String apiKey,
        String privacyLevel,
        String aliasesCsv
) {
    /** True when this deployment is a cloud upstream (not a worker / logosnode). */
    public boolean isCloud() {
        String type = providerType == null ? "" : providerType.strip().toLowerCase(java.util.Locale.ROOT);
        return "cloud".equals(type);
    }

    /**
     * True when the upstream needs Anthropic Messages dialect translation
     * (or Azure Anthropic) that Phase 1 does not implement in the gateway.
     */
    public boolean needsAnthropicDialect() {
        String cloud = cloudProviderType == null ? ""
            : cloudProviderType.strip().toLowerCase(java.util.Locale.ROOT);
        if ("anthropic".equals(cloud)) {
            return true;
        }
        String ep = endpoint == null ? "" : endpoint.split("\\?", 2)[0].replaceAll("/+$", "");
        return ep.endsWith("/anthropic/v1/messages");
    }
}
