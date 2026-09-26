package de.tum.cit.aet.logos.logoswebservice.gateway;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class CloudForwardUrlBuilderTest {

    private static final String AZURE_BASE = "https://ase-se01.openai.azure.com/openai/deployments/";
    private static final String AZURE_ENDPOINT =
        "https://ase-se01.openai.azure.com/openai/deployments/"
            + "gpt-41-mini/chat/completions?api-version=2025-01-01-preview";

    @Test
    void absoluteAzureEndpointUsedVerbatim() {
        assertThat(CloudForwardUrlBuilder.build(AZURE_BASE, "/v1/chat/completions", AZURE_ENDPOINT))
            .isEqualTo(AZURE_ENDPOINT);
    }

    @Test
    void absoluteEndpointUsedWhenNoRequestPath() {
        assertThat(CloudForwardUrlBuilder.build(AZURE_BASE, null, AZURE_ENDPOINT))
            .isEqualTo(AZURE_ENDPOINT);
    }

    @Test
    void openaiShapedUpstreamForwardsLikeForLike() {
        assertThat(CloudForwardUrlBuilder.build(
                "https://api.openai.com/v1", "/v1/chat/completions", ""))
            .isEqualTo("https://api.openai.com/v1/chat/completions");
    }

    @Test
    void relativeEndpointMergedWhenNoRequestPath() {
        assertThat(CloudForwardUrlBuilder.build(
                "https://api.openai.com/v1", null, "chat/completions"))
            .isEqualTo("https://api.openai.com/v1/chat/completions");
    }

    @Test
    void inboundResponsesPathRetargetsAzureChatEndpoint() {
        assertThat(CloudForwardUrlBuilder.build(AZURE_BASE, "v1/responses", AZURE_ENDPOINT))
            .isEqualTo(
                "https://ase-se01.openai.azure.com/openai/deployments/"
                    + "gpt-41-mini/responses?api-version=2025-04-01-preview");
    }

    @Test
    void inboundChatPathRetargetsAzureResponsesEndpoint() {
        String responsesEndpoint =
            "https://ase-se01.openai.azure.com/openai/deployments/"
                + "gpt-4o/responses?api-version=2025-04-01-preview";
        assertThat(CloudForwardUrlBuilder.build(AZURE_BASE, "v1/chat/completions", responsesEndpoint))
            .isEqualTo(
                "https://ase-se01.openai.azure.com/openai/deployments/"
                    + "gpt-4o/chat/completions?api-version=2025-01-01-preview");
    }

    @Test
    void matchingOperationLeftUntouched() {
        assertThat(CloudForwardUrlBuilder.build(AZURE_BASE, "v1/chat/completions", AZURE_ENDPOINT))
            .isEqualTo(AZURE_ENDPOINT);
    }

    @Test
    void nonSwappableOperationsLeftUntouched() {
        String embeddings =
            "https://ase-se01.openai.azure.com/openai/deployments/"
                + "text-embedding-3-large/embeddings?api-version=2024-02-01";
        assertThat(CloudForwardUrlBuilder.build(AZURE_BASE, "v1/responses", embeddings))
            .isEqualTo(embeddings);
        assertThat(CloudForwardUrlBuilder.build(AZURE_BASE, "v1/embeddings", AZURE_ENDPOINT))
            .isEqualTo(AZURE_ENDPOINT);
    }

    @Test
    void inboundTranslationPathRetargetsAzureWhisperEndpoint() {
        String transcriptionEndpoint =
            "https://ase-se01.openai.azure.com/openai/deployments/"
                + "whisper/audio/transcriptions?api-version=2025-04-01-preview";
        assertThat(CloudForwardUrlBuilder.build(
                AZURE_BASE, "v1/audio/translations", transcriptionEndpoint))
            .isEqualTo(
                "https://ase-se01.openai.azure.com/openai/deployments/"
                    + "whisper/audio/translations?api-version=2025-04-01-preview");
    }

    @Test
    void openaiShapedUpstreamForwardsResponsesLikeForLike() {
        assertThat(CloudForwardUrlBuilder.build(
                "https://api.openai.com/v1", "/v1/responses", ""))
            .isEqualTo("https://api.openai.com/v1/responses");
    }

    @Test
    void azureResponsesRouteCollapsesAndExtractsDeployment() {
        String url =
            "https://ase-se01.openai.azure.com/openai/deployments/gpt-4o/responses"
                + "?api-version=2025-04-01-preview";
        var rewrite = CloudForwardUrlBuilder.azureResponsesRewrite(url);
        assertThat(rewrite).isPresent();
        assertThat(rewrite.get().realUrl())
            .isEqualTo("https://ase-se01.openai.azure.com/openai/responses?api-version=2025-04-01-preview");
        assertThat(rewrite.get().deploymentId()).isEqualTo("gpt-4o");
    }

    @Test
    void azureResponsesRouteIgnoresChatCompletions() {
        assertThat(CloudForwardUrlBuilder.azureResponsesRewrite(AZURE_ENDPOINT)).isEmpty();
    }
}
