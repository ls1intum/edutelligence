package de.tum.cit.aet.logos.logoswebservice.admin;

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
import org.springframework.test.web.servlet.MvcResult;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fasterxml.jackson.databind.ObjectMapper;

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
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class ExportImportControllerTest {

    @Autowired MockMvc mvc;
    @Autowired ObjectMapper objectMapper;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void export_requiresLogosAdmin() throws Exception {
        mvc.perform(post("/logosdb/export")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void export_logosAdminReturnsAllTables() throws Exception {
        mvc.perform(post("/logosdb/export")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").isMap())
           .andExpect(jsonPath("$.result.users").isArray())
           .andExpect(jsonPath("$.result.models").isArray())
           .andExpect(jsonPath("$.result.providers").isArray());
    }

    @Test
    void importExport_roundtrip() throws Exception {
        MvcResult exportResult = mvc.perform(post("/logosdb/export")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andReturn();

        String exportBody = exportResult.getResponse().getContentAsString();
        @SuppressWarnings("unchecked")
        java.util.Map<String, Object> exportData =
            objectMapper.readValue(exportBody, java.util.Map.class);
        Object tableData = exportData.get("result");

        String importBody = objectMapper.writeValueAsString(
            java.util.Map.of("json_data", tableData));

        mvc.perform(post("/logosdb/import")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content(importBody))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Import successful"));
    }
}
