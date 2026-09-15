package de.tum.cit.aet.logos.logoswebservice.operations;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import de.tum.cit.aet.logos.logoswebservice.operations.controller.ProviderPerformanceController;
import de.tum.cit.aet.logos.logoswebservice.operations.dto.RunModelBenchmarkRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.operations.service.ProviderPerformanceService;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorWorkerAdminClient;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.*;

class BenchmarkBatchForwardingTest {
    @Test
    void preservesNestedBatchSettingsFromSnakeCaseRequest() throws Exception {
        ObjectMapper mapper = new ObjectMapper().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);
        RunModelBenchmarkRequestDTO request = mapper.readValue("""
            {"model_provider_id":7,"sample_size":50,"batch":{"repetitions":20,
             "configurations":[{"concurrency":4,"samples":50,"serving_overrides":{"tensor_parallel_size":2}}]}}
            """, RunModelBenchmarkRequestDTO.class);
        OrchestratorWorkerAdminClient client = mock(OrchestratorWorkerAdminClient.class);
        when(client.startModelBenchmark(7, 50, 512, Map.of("batch", request.batch())))
            .thenReturn(ResponseEntity.accepted().body(Map.of("job_id", 42)));
        var controller = new ProviderPerformanceController(mock(ProviderPerformanceService.class), client, mapper);
        assertEquals(202, controller.runModelBenchmark(request).getStatusCode().value());
        verify(client).startModelBenchmark(7, 50, 512, Map.of("batch", request.batch()));
        assertEquals(20, request.batch().get("repetitions"));
    }
}
