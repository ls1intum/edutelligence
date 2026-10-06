package de.tum.cit.aet.logos.logoswebservice.admin.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
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
    void normalizeRecommendationsDefaultsModelSetByOwnerForOlderDumps() {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("id", 9);
        row.put("recommended_sla", "ux-critical");
        List<Map<String, Object>> out =
            service.normalizeImportRows("ai_llm_call_recommendations", List.of(row));
        assertEquals(false, out.get(0).get("model_set_by_owner"));
        assertEquals(false, out.get(0).get("review_carried_over"));
    }

    @Test
    void normalizeAnalysesKeepsOnlyTheNewestInFlightPerRepository() {
        List<Map<String, Object>> rows = List.of(
            analysis(1, 7, "queued"), analysis(2, 7, "running"), analysis(3, 7, "succeeded"),
            analysis(4, 8, "queued"));
        List<Map<String, Object>> out = service.normalizeImportRows("ai_workflow_analyses", rows);
        assertEquals(List.of("failed", "running", "succeeded", "queued"),
            out.stream().map(r -> r.get("status")).toList());
        assertEquals("superseded by a newer queued analysis", out.get(0).get("error"));
    }

    private static Map<String, Object> analysis(int id, int repo, String status) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("id", id);
        row.put("team_repository_id", repo);
        row.put("status", status);
        row.put("started_at", "2026-10-01T10:00:00Z");
        return row;
    }

    @Test
    void normalizeEmptyRowsReturnsEmpty() {
        assertTrue(service.normalizeImportRows("models", null).isEmpty());
        assertTrue(service.normalizeImportRows("models", List.of()).isEmpty());
    }

    @Test
    void importAcceptsExportWithoutProviderBudgets() {
        Map<String, Object> data = allTables();
        data.remove("team_provider_budgets");
        ExportImportService.requireTables(data);
    }

    @Test
    void importRejectsExportMissingARequiredTable() {
        Map<String, Object> data = allTables();
        data.remove("teams");
        IllegalArgumentException e = assertThrows(
            IllegalArgumentException.class, () -> ExportImportService.requireTables(data));
        assertTrue(e.getMessage().contains("teams"));
    }

    private static Map<String, Object> allTables() {
        Map<String, Object> data = new LinkedHashMap<>();
        for (String table : ExportImportService.TABLES) {
            data.put(table, List.of());
        }
        return data;
    }
}
