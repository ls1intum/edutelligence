package de.tum.cit.aet.logos.logoswebservice.operations.service;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.LinkedHashMap;
import java.util.Map;

import org.junit.jupiter.api.Test;

class RequestLogServiceTokenCountsTest {

    @Test
    void measuredPromptWinsOverEstimate() {
        Map<String, Object> row = new LinkedHashMap<>();
        RequestLogService.putTokenCounts(row, 40L, 12L, 5L, 45L);

        assertThat(row.get("prompt_tokens")).isEqualTo(40L);
        assertThat(row.get("prompt_estimated")).isEqualTo(false);
        assertThat(row.get("completion_tokens")).isEqualTo(5L);
        assertThat(row.get("total_tokens")).isEqualTo(45L);
    }

    @Test
    void estimatedPromptSurfacesWhenUpstreamReportedNone() {
        Map<String, Object> row = new LinkedHashMap<>();
        RequestLogService.putTokenCounts(row, null, 1200L, null, null);

        assertThat(row.get("prompt_tokens")).isEqualTo(1200L);
        assertThat(row.get("prompt_estimated")).isEqualTo(true);
        assertThat(row.get("completion_tokens")).isNull();
        assertThat(row.get("total_tokens")).isEqualTo(1200L);
    }

    @Test
    void blankWhenNeitherMeasuredNorEstimated() {
        Map<String, Object> row = new LinkedHashMap<>();
        RequestLogService.putTokenCounts(row, null, null, null, null);

        assertThat(row.get("prompt_tokens")).isNull();
        assertThat(row.get("prompt_estimated")).isEqualTo(false);
        assertThat(row.get("completion_tokens")).isNull();
        assertThat(row.get("total_tokens")).isNull();
    }
}
