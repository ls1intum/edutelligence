package de.tum.cit.aet.logos.logoswebservice.operations;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.TestJwt;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestContainersConfig.class)
@TestPropertySource(properties = {
    "spring.liquibase.enabled=true",
    "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml",
    "logos.auth.roles.logos-admin=itg-admin",
    "logos.auth.roles.app-admin=chair-member",
    "logos.auth.sync-debounce-minutes=5"
})
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql", "/sql/seed-operations.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-operations.sql", "/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class VramControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void getVramStats_returnsProvidersArray() throws Exception {
        mvc.perform(post("/logosdb/get_ollama_vram_stats")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.providers").isArray())
           .andExpect(jsonPath("$.providers[0].provider_id").isNumber())
           .andExpect(jsonPath("$.providers[0].data").isArray());
    }

    @Test
    void getVramStats_withExplicitDay_returnsProviders() throws Exception {
        String today = java.time.LocalDate.now(java.time.ZoneOffset.UTC).toString();
        mvc.perform(post("/logosdb/get_ollama_vram_stats")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"day\": \"" + today + "\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.providers").isArray());
    }

    @Test
    void getVramStats_downsamplesToLatestSnapshotPerMinute() throws Exception {

        mvc.perform(post("/logosdb/get_ollama_vram_stats")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"day\": \"2024-06-01\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.providers.length()").value(1))
           .andExpect(jsonPath("$.providers[0].data.length()").value(2))
           .andExpect(jsonPath("$.providers[0].data[0].snapshot_id").value(4003))
           .andExpect(jsonPath("$.providers[0].data[1].snapshot_id").value(4004))
           .andExpect(jsonPath("$.last_snapshot_id").value(4004));
    }

    @Test
    void getVramStats_secondResolution_keepsEverySnapshot() throws Exception {
        // resolution=second must bypass the per-minute downsampling: all three
        // seeded snapshots (10:00:05, 10:00:25, 10:01:10) are returned
        mvc.perform(post("/logosdb/get_ollama_vram_stats")
                .header("logos-key", "dev-key-1")
                .contentType("application/json")
                .content("{\"day\": \"2024-06-01\", \"resolution\": \"second\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.providers[0].data.length()").value(3))
           .andExpect(jsonPath("$.providers[0].data[0].snapshot_id").value(4002))
           .andExpect(jsonPath("$.providers[0].data[1].snapshot_id").value(4003))
           .andExpect(jsonPath("$.providers[0].data[2].snapshot_id").value(4004))
           .andExpect(jsonPath("$.last_snapshot_id").value(4004));
    }

    @Test
    void getVramStats_afterSnapshotId_returnsOnlyNewerSnapshots() throws Exception {
        mvc.perform(post("/logosdb/get_ollama_vram_stats")
                .header("logos-key", "dev-key-1")
                .contentType("application/json")
                .content("{\"day\": \"2024-06-01\", \"resolution\": \"second\", \"after_snapshot_id\": 4003}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.providers[0].data.length()").value(1))
           .andExpect(jsonPath("$.providers[0].data[0].snapshot_id").value(4004))
           .andExpect(jsonPath("$.last_snapshot_id").value(4004));
    }

    @Test
    void getVramStats_invalidResolution_returns400() throws Exception {
        mvc.perform(post("/logosdb/get_ollama_vram_stats")
                .header("logos-key", "dev-key-1")
                .contentType("application/json")
                .content("{\"resolution\": \"millisecond\"}"))
           .andExpect(status().isBadRequest());
    }

    @Test
    void getVramStats_futureDay_returns400() throws Exception {
        mvc.perform(post("/logosdb/get_ollama_vram_stats")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"day\": \"2099-01-01\"}"))
           .andExpect(status().isBadRequest());
    }

    @Test
    void getVramStats_rejectsUnauthenticated() throws Exception {
        mvc.perform(post("/logosdb/get_ollama_vram_stats")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isUnauthorized());
    }
}
