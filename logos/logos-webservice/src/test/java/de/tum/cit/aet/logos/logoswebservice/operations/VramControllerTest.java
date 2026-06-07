package de.tum.cit.aet.logos.logoswebservice.operations;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestContainersConfig.class)
@TestPropertySource(properties = {
    "spring.liquibase.enabled=true",
    "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml"
})
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql", "/sql/seed-operations.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-operations.sql", "/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class VramControllerTest {

    @Autowired MockMvc mvc;

    @Test
    void getVramStats_returnsProvidersArray() throws Exception {
        mvc.perform(post("/logosdb/get_ollama_vram_stats")
                .header("logos-key", "dev-key-1")
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
                .header("logos-key", "dev-key-1")
                .contentType("application/json")
                .content("{\"day\": \"" + today + "\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.providers").isArray());
    }

    @Test
    void getVramStats_futureDay_returns400() throws Exception {
        mvc.perform(post("/logosdb/get_ollama_vram_stats")
                .header("logos-key", "dev-key-1")
                .contentType("application/json")
                .content("{\"day\": \"2099-01-01\"}"))
           .andExpect(status().isBadRequest());
    }

    @Test
    void getVramStats_rejectsInvalidKey() throws Exception {
        mvc.perform(post("/logosdb/get_ollama_vram_stats")
                .header("logos-key", "bad-key")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isUnauthorized());
    }
}