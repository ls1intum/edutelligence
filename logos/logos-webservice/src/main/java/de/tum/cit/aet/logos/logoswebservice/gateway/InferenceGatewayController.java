package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.io.IOException;
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
 * <p>Authenticates Logos API keys (not JWT). Pure-cloud named-model traffic is
 * forwarded straight to the cloud provider; everything else is reverse-proxied
 * to the orchestrator.
 *
 * <p><b>Remaining process state</b> (gateway is otherwise stateless per request):
 * <ul>
 *   <li>{@link GatewayBudgetService}'s short-TTL budget usage/limit cache</li>
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
    private final GatewayOrchestratorProxy orchestratorProxy;
    private final ObjectMapper objectMapper;

    public InferenceGatewayController(
            @Value("${logos.gateway.enabled:true}") boolean enabled,
            GatewayAuthService authService,
            GatewayBudgetService budgetService,
            GatewayCloudAccounting cloudAccounting,
            GatewayCloudForwarder cloudForwarder,
            GatewayOrchestratorProxy orchestratorProxy,
            ObjectMapper objectMapper) {
        this.enabled = enabled;
        this.authService = authService;
        this.budgetService = budgetService;
        this.cloudAccounting = cloudAccounting;
        this.cloudForwarder = cloudForwarder;
        this.orchestratorProxy = orchestratorProxy;
        this.objectMapper = objectMapper;
    }

    @RequestMapping({"/v1", "/v1/**", "/openai", "/openai/**", "/jobs", "/jobs/**"})
    public ResponseEntity<StreamingResponseBody> handle(HttpServletRequest request) throws IOException {
        String apiKeyValue = GatewayApiKeyExtractor.extract(request);
        String path = pathWithinApp(request);
        byte[] body = request.getInputStream().readAllBytes();
        String modelName = extractModelName(body, request.getContentType());

        if (!enabled) {
            GatewayKey key = authService.requireActiveKey(apiKeyValue);
            log.debug("Gateway disabled — proxying {} {} keyId={} to orchestrator",
                request.getMethod(), path, key.id());
            return orchestratorProxy.proxy(request, path, body);
        }

        // Named-model inference: one SQL round-trip for auth + permissions.
        // Listing/jobs/resource-mode: key-only query, then proxy.
        String contentType = request.getContentType();
        boolean multipart = contentType != null
            && contentType.toLowerCase(Locale.ROOT).startsWith("multipart/");
        if (modelName != null
                && !path.startsWith("/jobs")
                && !GatewayRouteResolver.isListingOrWarmupPath(path, request.getMethod())
                && !multipart) {
            GatewayAuthContext ctx = authService.requireKeyAndDeployments(apiKeyValue, modelName);
            GatewayRouteDecision decision = GatewayRouteResolver.decideFromDeployments(
                ctx.deploymentsForModel());
            if (decision.route() == GatewayRoute.CLOUD && decision.deployment() != null
                    && !GatewayRouteResolver.isMessagesPath(path)) {
                budgetService.enforceCloudBudget(ctx.key());
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
            log.debug("Orchestrator proxy {} {} reason={}", request.getMethod(), path, decision.reason());
            return orchestratorProxy.proxy(request, path, body);
        }

        authService.requireActiveKey(apiKeyValue);
        log.debug("Orchestrator proxy {} {} (non-named-model path)", request.getMethod(), path);
        return orchestratorProxy.proxy(request, path, body);
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
