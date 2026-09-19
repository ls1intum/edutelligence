package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Enumeration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import jakarta.servlet.http.HttpServletRequest;

/**
 * Public inference gateway for {@code /v1/**}, {@code /openai/**}, {@code /jobs/**}.
 *
 * <p>Authenticates Logos API keys (not JWT) <em>before</em> buffering the body.
 * Pure-cloud named-model traffic on an allowlisted inference path is forwarded
 * straight to the cloud provider; everything else is reverse-proxied to the
 * orchestrator.
 *
 * <p><b>Remaining process state</b> (gateway is otherwise stateless per request):
 * <ul>
 *   <li>{@link GatewayBudgetService}'s short-TTL budget usage/limit cache</li>
 *   <li>{@link GatewayCloudRateLimiter}'s per-key RPM/TPM windows</li>
 *   <li>JDK {@link java.net.http.HttpClient} connection pools in the forwarders</li>
 * </ul>
 *
 * <p>When {@code logos.gateway.enabled=false}, every request is proxied to the
 * orchestrator after API-key auth (safe fallback).
 */
@RestController
public class InferenceGatewayController {

    private static final Logger log = LoggerFactory.getLogger(InferenceGatewayController.class);

    private final boolean enabled;
    private final GatewayAuthService authService;
    private final GatewayBudgetService budgetService;
    private final GatewayCloudAccounting cloudAccounting;
    private final GatewayCloudForwarder cloudForwarder;
    private final GatewayCloudRateLimiter cloudRateLimiter;
    private final GatewayOrchestratorProxy orchestratorProxy;
    private final ObjectMapper objectMapper;

    public InferenceGatewayController(
            @Value("${logos.gateway.enabled:true}") boolean enabled,
            GatewayAuthService authService,
            GatewayBudgetService budgetService,
            GatewayCloudAccounting cloudAccounting,
            GatewayCloudForwarder cloudForwarder,
            GatewayCloudRateLimiter cloudRateLimiter,
            GatewayOrchestratorProxy orchestratorProxy,
            ObjectMapper objectMapper) {
        this.enabled = enabled;
        this.authService = authService;
        this.budgetService = budgetService;
        this.cloudAccounting = cloudAccounting;
        this.cloudForwarder = cloudForwarder;
        this.cloudRateLimiter = cloudRateLimiter;
        this.orchestratorProxy = orchestratorProxy;
        this.objectMapper = objectMapper;
    }

    @RequestMapping({"/v1", "/v1/**", "/openai", "/openai/**", "/jobs", "/jobs/**"})
    public ResponseEntity<StreamingResponseBody> handle(HttpServletRequest request) throws IOException {
        String apiKeyValue = GatewayApiKeyExtractor.extract(request);
        String path = pathWithinApp(request);

        // Authenticate before buffering the body so unauthenticated traffic
        // cannot force large heap allocations on permitAll routes.
        if (!enabled) {
            GatewayKey key = authService.requireActiveKey(apiKeyValue);
            byte[] body = request.getInputStream().readAllBytes();
            log.debug("Gateway disabled — proxying {} {} keyId={} to orchestrator",
                request.getMethod(), path, key.id());
            return orchestratorProxy.proxy(request, path, body);
        }

        String contentType = request.getContentType();
        boolean multipart = contentType != null
            && contentType.toLowerCase(Locale.ROOT).startsWith("multipart/");

        // Multipart: auth then stream via proxy without a model peek.
        if (multipart || path.startsWith("/jobs")
                || GatewayRouteResolver.isListingOrWarmupPath(path, request.getMethod())) {
            authService.requireActiveKey(apiKeyValue);
            byte[] body = request.getInputStream().readAllBytes();
            log.debug("Orchestrator proxy {} {} (listing/jobs/multipart)", request.getMethod(), path);
            return orchestratorProxy.proxy(request, path, body);
        }

        // Named-model path: key-only auth first, then body, then deployments.
        GatewayKey key = authService.requireActiveKey(apiKeyValue);
        byte[] body = request.getInputStream().readAllBytes();
        String modelName = extractModelName(body, contentType);

        if (modelName != null
                && GatewayRouteResolver.isDirectCloudEligible(path, request.getMethod())
                && !GatewayRouteResolver.isMessagesPath(path)
                && !requiresOrchestratorPolicy(request, modelName)) {
            GatewayAuthContext ctx = new GatewayAuthContext(
                key, authService.deploymentsForModel(key, modelName));
            List<GatewayDeployment> privacyFiltered = filterByPrivacy(
                ctx.deploymentsForModel(), request, modelName);
            GatewayRouteDecision decision = GatewayRouteResolver.decideFromDeployments(privacyFiltered);
            if (decision.route() == GatewayRoute.CLOUD && decision.deployment() != null) {
                budgetService.enforceCloudBudget(ctx.key());
                cloudRateLimiter.enforceAndRecord(ctx.key(), body);
                Integer logId = cloudAccounting.reserve(ctx.key(), decision.deployment());
                String inferencePath = GatewayRouteResolver.normalizeInferencePath(path);
                log.debug("Cloud forward {} {} model={} reason={}",
                    request.getMethod(), path, modelName, decision.reason());
                return cloudForwarder.forward(
                    decision.deployment(),
                    inferencePath,
                    request.getQueryString(),
                    request.getMethod(),
                    body,
                    copyHeaders(request),
                    () -> cloudAccounting.settleSuccess(logId),
                    err -> cloudAccounting.settleFailure(logId, err));
            }
            log.debug("Orchestrator proxy {} {} reason={}",
                request.getMethod(), path, decision.reason());
            return orchestratorProxy.proxy(request, path, body);
        }

        log.debug("Orchestrator proxy {} {} keyId={} (non-cloud-eligible path)",
            request.getMethod(), path, key.id());
        return orchestratorProxy.proxy(request, path, body);
    }

    /**
     * Policy-bearing requests stay on the orchestrator so threshold_privacy and
     * stored policies apply. Direct cloud uses the default cloud threshold only.
     */
    private static boolean requiresOrchestratorPolicy(HttpServletRequest request, String modelName) {
        if (headerPresent(request, "policy")) {
            return true;
        }
        return modelName != null && modelName.regionMatches(true, 0, "logos-v", 0, 7);
    }

    private static boolean headerPresent(HttpServletRequest request, String name) {
        Enumeration<String> values = request.getHeaders(name);
        return values != null && values.hasMoreElements();
    }

    private static List<GatewayDeployment> filterByPrivacy(
            List<GatewayDeployment> deployments, HttpServletRequest request, String modelName) {
        if (deployments == null || deployments.isEmpty()) {
            return List.of();
        }
        String threshold = GatewayPrivacy.DEFAULT_THRESHOLD;
        // logos-v* already diverted; keep default threshold for plain named models.
        List<GatewayDeployment> out = new ArrayList<>();
        for (GatewayDeployment d : deployments) {
            if (GatewayPrivacy.privacyOk(threshold, d.privacyLevel())) {
                out.add(d);
            }
        }
        if (out.isEmpty()) {
            logPrivacyDivert(modelName, threshold, deployments.size());
        }
        return out;
    }

    private static void logPrivacyDivert(String modelName, String threshold, int before) {
        LoggerFactory.getLogger(InferenceGatewayController.class)
            .debug("Privacy filter removed all {} deployments for model={} threshold={}",
                before, modelName, threshold);
    }

    private String extractModelName(byte[] body, String contentType) {
        if (body == null || body.length == 0) {
            return null;
        }
        if (contentType != null && contentType.toLowerCase(Locale.ROOT).startsWith("multipart/")) {
            return null;
        }
        try {
            JsonNode root = objectMapper.readTree(body);
            JsonNode model = root.get("model");
            if (model == null || model.isNull()) {
                return null;
            }
            String value = model.asText(null);
            return value == null || value.isBlank() ? null : value.strip();
        } catch (Exception e) {
            return null;
        }
    }

    private static String pathWithinApp(HttpServletRequest request) {
        String uri = request.getRequestURI();
        String context = request.getContextPath();
        if (context != null && !context.isEmpty() && uri.startsWith(context)) {
            uri = uri.substring(context.length());
        }
        return uri.isEmpty() ? "/" : uri;
    }

    private static Map<String, List<String>> copyHeaders(HttpServletRequest request) {
        Map<String, List<String>> headers = new LinkedHashMap<>();
        Enumeration<String> names = request.getHeaderNames();
        if (names == null) {
            return headers;
        }
        while (names.hasMoreElements()) {
            String name = names.nextElement();
            headers.put(name, Collections.list(request.getHeaders(name)));
        }
        return headers;
    }
}
