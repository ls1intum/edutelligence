package de.tum.cit.aet.logos.logoswebservice.identity.service;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.HashSet;
import java.util.Set;

import org.junit.jupiter.api.Test;

class AiWorkflowTagTest {

    @Test
    void uniqueTagKeepsAFreeBaseAndReservesIt() {
        Set<String> taken = new HashSet<>();
        assertThat(AiWorkflowAnalysisService.uniqueTag("checkout", taken)).isEqualTo("checkout");
        assertThat(AiWorkflowAnalysisService.uniqueTag("checkout", taken)).isEqualTo("checkout-2");
        assertThat(AiWorkflowAnalysisService.uniqueTag("checkout", taken)).isEqualTo("checkout-3");
    }

    @Test
    void uniqueTagStaysWithinTheLimitAndDistinctAfterTruncation() {
        String workflowTag = "w".repeat(80);
        Set<String> taken = new HashSet<>(Set.of(workflowTag));
        String first = AiWorkflowAnalysisService.uniqueTag(workflowTag + "-score", taken);
        String second = AiWorkflowAnalysisService.uniqueTag(workflowTag + "-summarize", taken);
        assertThat(first).hasSizeLessThanOrEqualTo(80).isNotEqualTo(workflowTag);
        assertThat(second).hasSizeLessThanOrEqualTo(80).isNotEqualTo(first).isNotEqualTo(workflowTag);
    }

    @Test
    void normalizeTagMatchesTheIngestShape() {
        assertThat(AiWorkflowAnalysisService.normalizeTag(" Checkout.Pay ")).isEqualTo("checkoutpay");
        assertThat(AiWorkflowAnalysisService.normalizeTag("  ")).isNull();
        assertThat(AiWorkflowAnalysisService.normalizeTag("a".repeat(100))).hasSize(80);
    }
}
