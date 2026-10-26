package de.tum.cit.aet.logos.logoswebservice.configuration;

import java.util.Map;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.json.JacksonJsonHttpMessageConverter;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import com.fasterxml.jackson.databind.ObjectMapper;
import tools.jackson.databind.PropertyNamingStrategies;
import tools.jackson.databind.json.JsonMapper;

import de.tum.cit.aet.logos.logoswebservice.audit.AuditLogService;
import de.tum.cit.aet.logos.logoswebservice.configuration.controller.ProviderController;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.LaneLockService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelCapabilitiesUpdaterService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.PriceUpdaterService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ProviderService;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorModelSyncClient;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorWorkerAdminClient;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** HTTP mappings and JSON binding; role enforcement is covered by ProviderControllerTest. */
class ProviderMaintenanceRoutesTest {

    private MockMvc mvc;
    private OrchestratorWorkerAdminClient workerAdminClient;

    @BeforeEach
    void setUp() {
        workerAdminClient = mock(OrchestratorWorkerAdminClient.class);
        var controller = new ProviderController(
            mock(ProviderService.class), mock(PriceUpdaterService.class),
            mock(ModelCapabilitiesUpdaterService.class), mock(ModelRepository.class),
            workerAdminClient, mock(OrchestratorModelSyncClient.class), new ObjectMapper(),
            mock(LaneLockService.class), mock(AuditLogService.class));
        var json = JsonMapper.builder().propertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE).build();
        mvc = MockMvcBuilders.standaloneSetup(controller)
            .setMessageConverters(new JacksonJsonHttpMessageConverter(json))
            .build();
    }

    @ParameterizedTest
    @ValueSource(strings = {"/logosdb/maintenance", "/logosdb/providers/logosnode/maintenance"})
    void statusReturnsTheOrchestratorView(String path) throws Exception {
        when(workerAdminClient.maintenanceStatus())
            .thenReturn(ResponseEntity.ok(Map.of("free", true, "limit", 1)));

        mvc.perform(get(path))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.free").value(true))
            .andExpect(jsonPath("$.limit").value(1));
        verify(workerAdminClient).maintenanceStatus();
    }

    @ParameterizedTest
    @ValueSource(strings = {"/logosdb/maintenance", "/logosdb/providers/logosnode/maintenance"})
    void calibrationReleaseForwardsTheClaim(String path) throws Exception {
        when(workerAdminClient.releaseCalibrationClaim(12, "claim-1"))
            .thenReturn(ResponseEntity.ok(Map.of("released", true, "forced", false)));

        mvc.perform(post(path + "/release_calibration")
                .contentType("application/json")
                .content("{\"provider_id\":12,\"claim_token\":\"claim-1\"}"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.released").value(true));
        verify(workerAdminClient).releaseCalibrationClaim(12, "claim-1");
    }

    @ParameterizedTest
    @ValueSource(strings = {"/logosdb/maintenance", "/logosdb/providers/logosnode/maintenance"})
    void recoveryReleaseForwardsTheDeploymentAndForce(String path) throws Exception {
        when(workerAdminClient.releaseRecovery(31, true))
            .thenReturn(ResponseEntity.ok(Map.of("released", true, "forced", true)));

        mvc.perform(post(path + "/release_recovery")
                .contentType("application/json")
                .content("{\"model_provider_id\":31,\"force\":true}"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.forced").value(true));
        verify(workerAdminClient).releaseRecovery(31, true);
    }
}
