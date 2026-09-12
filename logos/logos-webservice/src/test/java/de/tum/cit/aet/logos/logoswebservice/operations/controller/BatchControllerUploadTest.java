package de.tum.cit.aet.logos.logoswebservice.operations.controller;

import java.nio.charset.StandardCharsets;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.TestJwt;
import de.tum.cit.aet.logos.logoswebservice.operations.service.BatchService;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * The upload limit, end to end: Spring's default rejects a per-file upload
 * above 1 MiB before the controller runs, while the orchestrator — whose
 * 50 MiB cap is what the batch page documents — would accept it. The limits
 * in application.properties mirror the orchestrator's; this pins them with a
 * file the default would have refused.
 */
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestContainersConfig.class)
@TestPropertySource(properties = {
    "spring.liquibase.enabled=true",
    "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml",
    "logos.auth.roles.logos-admin=itg-admin",
    "logos.auth.roles.app-admin=chair-member",
    "logos.auth.sync-debounce-minutes=5",
    "logos.orchestrator.url=",
    "logos.orchestrator.internal-secret="
})
@Sql(scripts = {"/sql/seed-identity.sql"}, executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-identity.sql"}, executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class BatchControllerUploadTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;
    @MockitoBean BatchService batchService;

    @Test
    void an_upload_larger_than_the_spring_default_reaches_the_service_intact() throws Exception {
        byte[] content = new byte[2 * 1024 * 1024];
        when(batchService.createBatch(anyInt(), anyInt(), anyString(), any(byte[].class), any(), any(), any()))
            .thenReturn(new BatchService.ProxiedResponse(
                200, "application/json", "{\"id\":\"batch_1\"}".getBytes(StandardCharsets.UTF_8)));

        mvc.perform(multipart("/logosdb/batches")
                .file(new MockMultipartFile("file", "batch.jsonl", "application/jsonl", content))
                .param("apiKeyId", "3004")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk());

        // The whole file made the round trip to the orchestrator call, not a
        // truncated or rejected remnant of it.
        ArgumentCaptor<byte[]> contentCaptor = ArgumentCaptor.forClass(byte[].class);
        verify(batchService).createBatch(eq(1003), eq(3004), eq("batch.jsonl"), contentCaptor.capture(), any(), any(), any());
        assertThat(contentCaptor.getValue()).hasSize(2 * 1024 * 1024);
    }
}
