package de.tum.cit.aet.logos.logoswebservice.gateway;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.Collections;

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

    @Test
    void preservesRepeatedQueryParameters() {
        assertThat(GatewayQueryMerge.merge("https://api.example/v1", "tag=a&tag=b"))
            .isEqualTo("https://api.example/v1?tag=a&tag=b");
        assertThat(GatewayQueryMerge.merge(
                "https://api.example/v1?keep=1&tag=old", "tag=a&tag=b"))
            .isEqualTo("https://api.example/v1?keep=1&tag=a&tag=b");
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

    @Test
    void requestExcludeIncludesConnectionNominated() {
        Set<String> exclude = GatewayHopByHop.requestExcludeNames(
            Collections.enumeration(List.of("close, X-Custom")));
        assertThat(exclude).contains("connection", "x-custom", "close", "expect");
        assertThat(exclude).doesNotContain("authorization");
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
                "https://api.anthropic.com", "", "x-api-key", "{}", "k",
                "CLOUD_NOT_IN_EU_BY_US_PROVIDER", null);
            assertThat(d.isCloud()).isTrue();
            assertThat(d.needsAnthropicDialect()).isTrue();
        } finally {
            Locale.setDefault(previous);
        }
    }
}

class GatewayModelNameResolverTest {

    @Test
    void resolvesCaseInsensitiveCanonicalAndAlias() {
        var models = List.of(
            GatewayModelNameResolver.ModelNames.of("gpt-4o", "Local-Most-Powerful"),
            GatewayModelNameResolver.ModelNames.of("Qwen/Qwen2.5-0.5B", null)
        );
        assertThat(GatewayModelNameResolver.resolve("GPT-4O", models)).isEqualTo("gpt-4o");
        assertThat(GatewayModelNameResolver.resolve("local-most-powerful", models)).isEqualTo("gpt-4o");
    }

    @Test
    void resolvesPlannerAliasAndReplica() {
        var models = List.of(
            GatewayModelNameResolver.ModelNames.of("Qwen/Qwen2.5-0.5B", null),
            GatewayModelNameResolver.ModelNames.of("llama", null),
            GatewayModelNameResolver.ModelNames.of("llama-3", null)
        );
        assertThat(GatewayModelNameResolver.resolve("planner-Qwen_Qwen2.5-0.5B", models))
            .isEqualTo("Qwen/Qwen2.5-0.5B");
        assertThat(GatewayModelNameResolver.resolve("planner-llama-3", models)).isEqualTo("llama-3");
        assertThat(GatewayModelNameResolver.resolve("planner-llama-2", models)).isEqualTo("llama");
    }

    @Test
    void refusesAmbiguousPlannerAlias() {
        var models = List.of(
            GatewayModelNameResolver.ModelNames.of("llama/2", null),
            GatewayModelNameResolver.ModelNames.of("llama:2", null)
        );
        assertThat(GatewayModelNameResolver.resolve("planner-llama_2", models)).isNull();
    }
}

class GatewayPrivacyTest {

    @Test
    void localDeploymentSatisfiesEveryThreshold() {
        assertThat(GatewayPrivacy.privacyOk("LOCAL", "LOCAL")).isTrue();
        assertThat(GatewayPrivacy.privacyOk("CLOUD_NOT_IN_EU_BY_US_PROVIDER", "LOCAL")).isTrue();
    }

    @Test
    void localThresholdRejectsCloudDeployment() {
        assertThat(GatewayPrivacy.privacyOk("LOCAL", "CLOUD_NOT_IN_EU_BY_US_PROVIDER")).isFalse();
    }
}

class GatewayDirectCloudAllowlistTest {

    @Test
    void allowsInferencePostsOnly() {
        assertThat(GatewayRouteResolver.isDirectCloudEligible("/v1/chat/completions", "POST")).isTrue();
        assertThat(GatewayRouteResolver.isDirectCloudEligible("/openai/embeddings", "POST")).isTrue();
        assertThat(GatewayRouteResolver.isDirectCloudEligible("/v1/files/abc", "DELETE")).isFalse();
        assertThat(GatewayRouteResolver.isDirectCloudEligible("/v1/files", "POST")).isFalse();
        assertThat(GatewayRouteResolver.isDirectCloudEligible("/v1/chat/completions", "GET")).isFalse();
    }
}
