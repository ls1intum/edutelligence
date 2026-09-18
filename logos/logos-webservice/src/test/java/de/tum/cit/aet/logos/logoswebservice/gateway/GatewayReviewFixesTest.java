package de.tum.cit.aet.logos.logoswebservice.gateway;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

import org.junit.jupiter.api.Test;

class GatewayQueryMergeTest {

    @Test
    void appendsWhenUrlHasNoQuery() {
        assertThat(GatewayQueryMerge.merge("https://api.example/v1/chat", "stream=true"))
            .isEqualTo("https://api.example/v1/chat?stream=true");
    }

    @Test
    void mergesInboundOntoAzureApiVersion() {
        String azure = "https://ase.openai.azure.com/openai/deployments/x/chat/completions?api-version=2025-01-01";
        assertThat(GatewayQueryMerge.merge(azure, "stream=true"))
            .isEqualTo(azure + "&stream=true");
    }

    @Test
    void inboundOverridesConflictingKey() {
        assertThat(GatewayQueryMerge.merge(
                "https://api.example/v1?api-version=old", "api-version=new&n=1"))
            .isEqualTo("https://api.example/v1?api-version=new&n=1");
    }

    @Test
    void blankInboundLeavesUrlUnchanged() {
        String url = "https://api.example/v1?api-version=1";
        assertThat(GatewayQueryMerge.merge(url, "  ")).isEqualTo(url);
        assertThat(GatewayQueryMerge.merge(url, null)).isEqualTo(url);
    }
}

class GatewayHopByHopTest {

    @Test
    void filtersExpectAsRequestHopByHop() {
        assertThat(GatewayHopByHop.isRequestHopByHop("Expect")).isTrue();
        assertThat(GatewayHopByHop.isRequestHopByHop("expect")).isTrue();
        assertThat(GatewayHopByHop.isRequestHopByHop("Authorization")).isFalse();
    }

    @Test
    void responseExcludeIncludesTrailerAndConnectionNominated() {
        Set<String> exclude = GatewayHopByHop.responseExcludeNames(Map.of(
            "Connection", List.of("close, X-Custom"),
            "Trailer", List.of("X-Status")
        ));
        assertThat(exclude).contains("trailer", "close", "x-custom");
        assertThat(exclude).doesNotContain("trailers");
    }
}

class GatewayDeploymentLocaleTest {

    @Test
    void anthropicDetectionUsesRootLocale() {
        Locale previous = Locale.getDefault();
        try {
            Locale.setDefault(Locale.forLanguageTag("tr-TR"));
            GatewayDeployment d = new GatewayDeployment(
                1, "m", 2, "p", "CLOUD", "ANTHROPIC",
                "https://api.anthropic.com", "", "x-api-key", "{}", "k");
            assertThat(d.isCloud()).isTrue();
            assertThat(d.needsAnthropicDialect()).isTrue();
        } finally {
            Locale.setDefault(previous);
        }
    }
}
