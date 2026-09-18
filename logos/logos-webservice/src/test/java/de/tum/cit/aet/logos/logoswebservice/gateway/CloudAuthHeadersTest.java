package de.tum.cit.aet.logos.logoswebservice.gateway;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class CloudAuthHeadersTest {

    @Test
    void anthropicDefaultsToXApiKey() {
        var header = CloudAuthHeaders.authHeader("", "", "sk-ant", "anthropic");
        assertThat(header).isPresent();
        assertThat(header.get().name()).isEqualTo("x-api-key");
        assertThat(header.get().value()).isEqualTo("sk-ant");
    }

    @Test
    void openaiDefaultsToBearer() {
        var header = CloudAuthHeaders.authHeader("", "", "sk-oai", "openai");
        assertThat(header).isPresent();
        assertThat(header.get().name()).isEqualTo("Authorization");
        assertThat(header.get().value()).isEqualTo("Bearer sk-oai");
    }

    @Test
    void explicitChoiceIsNeverOverridden() {
        var header = CloudAuthHeaders.authHeader("Authorization", "Bearer {}", "sk-ant", "anthropic");
        assertThat(header).isPresent();
        assertThat(header.get().name()).isEqualTo("Authorization");
        assertThat(header.get().value()).isEqualTo("Bearer sk-ant");
    }

    @Test
    void emptyKeyYieldsNoHeader() {
        assertThat(CloudAuthHeaders.authHeader("Authorization", "Bearer {}", "", "openai")).isEmpty();
        assertThat(CloudAuthHeaders.authHeader(null, null, null, "openai")).isEmpty();
    }

    @Test
    void anthropicRequiresVersionHeader() {
        assertThat(CloudAuthHeaders.protocolHeaders("anthropic"))
            .containsEntry("anthropic-version", CloudAuthHeaders.ANTHROPIC_VERSION);
        assertThat(CloudAuthHeaders.protocolHeaders("openai")).isEmpty();
        assertThat(CloudAuthHeaders.protocolHeaders(null)).isEmpty();
    }

    @Test
    void explicitHeaderNameWithoutFormatUsesBareKey() {
        var header = CloudAuthHeaders.authHeader("api-key", "", "secret", "azure");
        assertThat(header).isPresent();
        assertThat(header.get().name()).isEqualTo("api-key");
        assertThat(header.get().value()).isEqualTo("secret");
    }
}
