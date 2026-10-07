package de.tum.cit.aet.logos.logoswebservice.identity.service;

import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class AiWorkflowAnalysisServicePromptTest {

    @Test
    void manualQueueTemplateIncludesObjectivePriorityContract() {
        String task = AiWorkflowAnalysisService.ANALYSIS_TASK_TEMPLATE;
        assertTrue(task.contains("\"objective_priority\""),
            "manual queue template must request objective_priority");
        assertTrue(task.contains("full ranking of latency, quality, and price"),
            "manual queue template must document ranking semantics");
        assertTrue(task.contains("ux-critical"),
            "manual queue template must document SLO-derived defaults");
        String formatted = task.formatted("acme/app", "https://github.com/acme/app", "src");
        assertTrue(formatted.contains("objective_priority"));
        assertTrue(formatted.contains("Repository: acme/app"));
    }
}
