package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.List;
import java.util.Locale;

import org.springframework.stereotype.Service;

/**
 * Decides CLOUD vs ORCHESTRATOR for an authenticated inference request.
 *
 * <p>Cloud only when every permitted deployment for the named model is
 * {@code provider_type=cloud} and none needs Anthropic dialect support.
 * Listing endpoints, jobs, resource mode (no model), multipart uploads,
 * ambiguous / empty permission sets, and mixed cloud+local keys go to the
 * orchestrator.
 */
@Service
public class GatewayRouteResolver {

    private final GatewayDeploymentRepository deploymentRepository;

    public GatewayRouteResolver(GatewayDeploymentRepository deploymentRepository) {
        this.deploymentRepository = deploymentRepository;
    }

    /**
     * Resolve the route for a request that already authenticated {@code apiKeyId}.
     *
     * @param pathWithinApp servlet path within the app (no context path), e.g. {@code /v1/chat/completions}
     * @param httpMethod    upper-case method
     * @param modelName     body {@code model} field, or null / blank when absent
     * @param contentType   request Content-Type, may be null
     */
    public GatewayRouteDecision resolve(
            int apiKeyId,
            String pathWithinApp,
            String httpMethod,
            String modelName,
            String contentType) {
        String path = pathWithinApp == null ? "" : pathWithinApp;
        String method = httpMethod == null ? "" : httpMethod.toUpperCase(Locale.ROOT);

        if (path.startsWith("/jobs")) {
            return GatewayRouteDecision.orchestrator("jobs");
        }
        if (isListingOrWarmupPath(path, method)) {
            return GatewayRouteDecision.orchestrator("listing-or-warmup");
        }
        if (contentType != null && contentType.toLowerCase(Locale.ROOT).startsWith("multipart/")) {
            return GatewayRouteDecision.orchestrator("multipart");
        }
        if (modelName == null || modelName.isBlank()) {
            return GatewayRouteDecision.orchestrator("resource-mode-no-model");
        }
        if (isMessagesPath(path)) {
            // Anthropic Messages dialect translation lives in the orchestrator.
            return GatewayRouteDecision.orchestrator("messages-path");
        }

        return decideFromDeployments(
            deploymentRepository.findPermittedDeploymentsForModel(apiKeyId, modelName.strip()));
    }

    /**
     * Pure decision over already-loaded deployments (unit-testable without DB).
     */
    public static GatewayRouteDecision decideFromDeployments(List<GatewayDeployment> deployments) {
        if (deployments == null || deployments.isEmpty()) {
            // Orchestrator owns the 404 wording / worker-wait behaviour.
            return GatewayRouteDecision.orchestrator("no-permitted-deployments");
        }
        for (GatewayDeployment d : deployments) {
            if (!d.isCloud()) {
                return GatewayRouteDecision.orchestrator("has-non-cloud-deployment");
            }
            if (d.needsAnthropicDialect()) {
                return GatewayRouteDecision.orchestrator("anthropic-dialect");
            }
        }
        // All cloud and OpenAI-shaped: pick the first (lowest provider id from SQL ORDER BY).
        GatewayDeployment chosen = deployments.get(0);
        return GatewayRouteDecision.cloud(chosen, "all-cloud");
    }

    static boolean isListingOrWarmupPath(String path, String method) {
        String p = stripOpenAiPrefix(path);
        if ("GET".equals(method) && (p.equals("/v1/models") || p.startsWith("/v1/models/"))) {
            return true;
        }
        if ("POST".equals(method) && p.matches("/v1/models/.+/warmup")) {
            return true;
        }
        // /openai/models mirrors /v1/models
        if ("GET".equals(method) && (path.equals("/openai/models") || path.startsWith("/openai/models/"))) {
            return true;
        }
        if ("POST".equals(method) && path.matches("/openai/models/.+/warmup")) {
            return true;
        }
        return false;
    }

    static boolean isMessagesPath(String path) {
        String p = stripOpenAiPrefix(path).replaceAll("/+$", "");
        return p.equals("/v1/messages") || p.endsWith("/messages") && p.contains("/v1/");
    }

    /**
     * Maps {@code /openai/chat/completions} → {@code /v1/chat/completions} the
     * way the orchestrator's {@code /openai/{path}} handler does.
     */
    public static String normalizeInferencePath(String pathWithinApp) {
        if (pathWithinApp == null || pathWithinApp.isEmpty()) {
            return pathWithinApp;
        }
        if (pathWithinApp.equals("/openai") || pathWithinApp.startsWith("/openai/")) {
            String rest = pathWithinApp.substring("/openai".length());
            if (rest.isEmpty() || rest.equals("/")) {
                return "/v1";
            }
            if (rest.startsWith("/v1/") || rest.equals("/v1") || rest.startsWith("/v2/") || rest.equals("/v2")) {
                return rest;
            }
            return "/v1" + rest;
        }
        return pathWithinApp;
    }

    /**
     * Paths eligible for direct-cloud forwarding. Everything else (files,
     * batches, DELETE, …) is proxied — even when a {@code model} field is
     * present — so provider credentials are not attached to non-inference APIs.
     */
    static boolean isDirectCloudEligible(String pathWithinApp, String httpMethod) {
        String method = httpMethod == null ? "" : httpMethod.toUpperCase(Locale.ROOT);
        if (!"POST".equals(method)) {
            return false;
        }
        String p = stripOpenAiPrefix(pathWithinApp).replaceAll("/+$", "");
        if (!p.startsWith("/v1/")) {
            return false;
        }
        String op = p.substring("/v1/".length());
        return switch (op) {
            case "chat/completions", "completions", "embeddings", "responses",
                 "images/generations", "images/edits", "images/variations",
                 "audio/speech", "audio/transcriptions", "audio/translations" -> true;
            default -> false;
        };
    }

    private static String stripOpenAiPrefix(String path) {
        return normalizeInferencePath(path);
    }
}
