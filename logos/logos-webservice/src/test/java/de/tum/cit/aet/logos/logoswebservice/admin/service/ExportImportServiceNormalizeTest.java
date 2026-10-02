package de.tum.cit.aet.logos.logoswebservice.admin.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.identity.ObjectivePriority;

class ExportImportServiceNormalizeTest {

    private final ExportImportService service =
        new ExportImportService(new JdbcTemplate(), new ObjectMapper());

    @Test
    void normalizeModelsFillsMissingProfileRatings() {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("id", 1);
        row.put("name", "gpt-fast");
        List<Map<String, Object>> out = service.normalizeImportRows("models", List.of(row));
        assertEquals(1, out.size());
        assertEquals(Map.of(), out.get(0).get("profile_ratings"));
    }

    @Test
    void normalizeModelsReplacesNullProfileRatings() {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("id", 1);
        row.put("name", "gpt-fast");
        row.put("profile_ratings", null);
        List<Map<String, Object>> out = service.normalizeImportRows("models", List.of(row));
        assertEquals(Map.of(), out.get(0).get("profile_ratings"));
    }

    @Test
    void normalizeRecommendationsFillsObjectivePriorityFromSla() {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("id", 9);
        row.put("recommended_sla", "ux-background");
        List<Map<String, Object>> out =
            service.normalizeImportRows("ai_llm_call_recommendations", List.of(row));
        assertEquals(
            ObjectivePriority.forSla("ux-background"),
            out.get(0).get("objective_priority"));
    }

    @Test
    void normalizeRecommendationsKeepsExistingObjectivePriority() {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("id", 9);
        row.put("recommended_sla", "ux-critical");
        row.put("objective_priority", List.of("quality", "price", "latency"));
        List<Map<String, Object>> out =
            service.normalizeImportRows("ai_llm_call_recommendations", List.of(row));
        assertEquals(List.of("quality", "price", "latency"), out.get(0).get("objective_priority"));
    }

    @Test
    void normalizeEmptyRowsReturnsEmpty() {
        assertTrue(service.normalizeImportRows("models", null).isEmpty());
        assertTrue(service.normalizeImportRows("models", List.of()).isEmpty());
    }
}
