package de.tum.cit.aet.logos.logoswebservice.gateway;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.util.List;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class GatewayRouteResolverTest {

    private GatewayDeploymentRepository repository;
    private GatewayRouteResolver resolver;

    @BeforeEach
    void setUp() {
        repository = mock(GatewayDeploymentRepository.class);
        resolver = new GatewayRouteResolver(repository);
    }

    @Test
    void jobsAlwaysGoToOrchestrator() {
        GatewayRouteDecision d = resolver.resolve(1, "/jobs/v1/chat/completions", "POST", "gpt-4", "application/json");
        assertThat(d.route()).isEqualTo(GatewayRoute.ORCHESTRATOR);
        assertThat(d.reason()).isEqualTo("jobs");
    }

    @Test
    void listingEndpointsGoToOrchestrator() {
        assertThat(resolver.resolve(1, "/v1/models", "GET", null, null).reason())
            .isEqualTo("listing-or-warmup");
        assertThat(resolver.resolve(1, "/openai/models", "GET", null, null).reason())
            .isEqualTo("listing-or-warmup");
    }

    @Test
    void noModelIsResourceMode() {
        assertThat(resolver.resolve(1, "/v1/chat/completions", "POST", null, "application/json").reason())
            .isEqualTo("resource-mode-no-model");
        assertThat(resolver.resolve(1, "/v1/chat/completions", "POST", "  ", "application/json").reason())
            .isEqualTo("resource-mode-no-model");
    }

    @Test
    void multipartGoesToOrchestrator() {
        assertThat(resolver.resolve(1, "/v1/audio/transcriptions", "POST", "whisper", "multipart/form-data").reason())
            .isEqualTo("multipart");
    }

    @Test
    void messagesPathGoesToOrchestrator() {
        assertThat(resolver.resolve(1, "/v1/messages", "POST", "claude", "application/json").reason())
            .isEqualTo("messages-path");
    }

    @Test
    void allCloudDeploymentsChooseCloud() {
        List<GatewayDeployment> deployments = List.of(
            cloud("openai", "https://api.openai.com/v1", ""),
            cloud("azure", "https://ase.openai.azure.com/", "https://ase.openai.azure.com/openai/deployments/x/chat/completions")
        );
        GatewayRouteDecision d = GatewayRouteResolver.decideFromDeployments(deployments);
        assertThat(d.route()).isEqualTo(GatewayRoute.CLOUD);
        assertThat(d.deployment()).isEqualTo(deployments.get(0));
        assertThat(d.reason()).isEqualTo("all-cloud");
    }

    @Test
    void mixedCloudAndLocalGoesToOrchestrator() {
        List<GatewayDeployment> deployments = List.of(
            cloud("openai", "https://api.openai.com/v1", ""),
            logosnode()
        );
        GatewayRouteDecision d = GatewayRouteResolver.decideFromDeployments(deployments);
        assertThat(d.route()).isEqualTo(GatewayRoute.ORCHESTRATOR);
        assertThat(d.reason()).isEqualTo("has-non-cloud-deployment");
    }

    @Test
    void anthropicDialectGoesToOrchestrator() {
        GatewayDeployment anthropic = new GatewayDeployment(
            1, "claude", 2, "Anthropic", "cloud", "anthropic",
            "https://api.anthropic.com", "", "x-api-key", "{}", "sk",
            "CLOUD_NOT_IN_EU_BY_US_PROVIDER", null);
        GatewayRouteDecision d = GatewayRouteResolver.decideFromDeployments(List.of(anthropic));
        assertThat(d.route()).isEqualTo(GatewayRoute.ORCHESTRATOR);
        assertThat(d.reason()).isEqualTo("anthropic-dialect");
    }

    @Test
    void emptyDeploymentsGoToOrchestrator() {
        assertThat(GatewayRouteResolver.decideFromDeployments(List.of()).reason())
            .isEqualTo("no-permitted-deployments");
    }

    @Test
    void resolveLoadsDeploymentsWhenNamedModel() {
        when(repository.findPermittedDeploymentsForModel(anyInt(), anyString()))
            .thenReturn(List.of(cloud("openai", "https://api.openai.com/v1", "")));
        GatewayRouteDecision d = resolver.resolve(9, "/v1/chat/completions", "POST", "gpt-4o", "application/json");
        assertThat(d.route()).isEqualTo(GatewayRoute.CLOUD);
    }

    @Test
    void normalizeOpenAiPrefix() {
        assertThat(GatewayRouteResolver.normalizeInferencePath("/openai/chat/completions"))
            .isEqualTo("/v1/chat/completions");
        assertThat(GatewayRouteResolver.normalizeInferencePath("/v1/chat/completions"))
            .isEqualTo("/v1/chat/completions");
        assertThat(GatewayRouteResolver.normalizeInferencePath("/openai/v1/embeddings"))
            .isEqualTo("/v1/embeddings");
    }

    private static GatewayDeployment cloud(String cloudType, String baseUrl, String endpoint) {
        return new GatewayDeployment(
            1, "gpt-4o", 10, "Cloud", "cloud", cloudType, baseUrl, endpoint, "Authorization", "Bearer {}", "sk",
            "CLOUD_NOT_IN_EU_BY_US_PROVIDER", null);
    }

    private static GatewayDeployment logosnode() {
        return new GatewayDeployment(
            1, "gpt-4o", 20, "Worker", "logosnode", null, "", "", "", "", "",
            "LOCAL", null);
    }
}
