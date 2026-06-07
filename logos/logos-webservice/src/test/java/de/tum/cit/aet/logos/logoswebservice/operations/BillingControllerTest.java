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
class BillingControllerTest {

    @Autowired MockMvc mvc;

    @Test
    void addBilling_logosAdminCanInsert() throws Exception {
        mvc.perform(post("/logosdb/add_billing")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("""
                    {"type_name":"prompt_tokens","type_cost":2000.0,"valid_from":"2025-01-01T00:00:00Z"}
                    """))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Successfully added billing"));
    }

    @Test
    void addBilling_nonAdminIsForbidden() throws Exception {
        mvc.perform(post("/logosdb/add_billing")
                .header("logos-key", "dev-key-1")
                .contentType("application/json")
                .content("""
                    {"type_name":"prompt_tokens","type_cost":1000.0,"valid_from":"2025-01-01T00:00:00Z"}
                    """))
           .andExpect(status().isForbidden());
    }

    @Test
    void addBilling_unknownTokenNameReturns500() throws Exception {
        mvc.perform(post("/logosdb/add_billing")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("""
                    {"type_name":"nonexistent_token","type_cost":1.0,"valid_from":"2025-01-01T00:00:00Z"}
                    """))
           .andExpect(status().isInternalServerError());
    }

    @Test
    void teamBudgetHistory_logosAdminCanQuery() throws Exception {
        mvc.perform(post("/logosdb/billing/team_budget_history")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("""
                    {"start_iso":"2020-01-01T00:00:00Z","end_iso":"2030-01-01T00:00:00Z"}
                    """))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.buckets").isArray())
           .andExpect(jsonPath("$.bucket_seconds").isNumber());
    }

    @Test
    void teamBudgetHistory_nonAdminIsForbidden() throws Exception {
        mvc.perform(post("/logosdb/billing/team_budget_history")
                .header("logos-key", "dev-key-1")
                .contentType("application/json")
                .content("""
                    {"start_iso":"2020-01-01T00:00:00Z","end_iso":"2030-01-01T00:00:00Z"}
                    """))
           .andExpect(status().isForbidden());
    }

    @Test
    void keyBudgetHistory_logosAdminCanQueryAnyTeam() throws Exception {
        mvc.perform(post("/logosdb/billing/key_budget_history/2001")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("""
                    {"start_iso":"2020-01-01T00:00:00Z","end_iso":"2030-01-01T00:00:00Z"}
                    """))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.buckets").isArray());
    }

    @Test
    void keyBudgetHistory_appAdminOwnerCanQueryOwnTeam() throws Exception {
        mvc.perform(post("/logosdb/billing/key_budget_history/2001")
                .header("logos-key", "admin-key-1")
                .contentType("application/json")
                .content("""
                    {"start_iso":"2020-01-01T00:00:00Z","end_iso":"2030-01-01T00:00:00Z"}
                    """))
           .andExpect(status().isOk());
    }

    @Test
    void keyBudgetHistory_appDeveloperIsForbiddenEvenAsOwner() throws Exception {
        mvc.perform(post("/logosdb/billing/key_budget_history/2001")
                .header("logos-key", "dev-key-1")
                .contentType("application/json")
                .content("""
                    {"start_iso":"2020-01-01T00:00:00Z","end_iso":"2030-01-01T00:00:00Z"}
                    """))
           .andExpect(status().isForbidden());
    }

    @Test
    void keyBudgetHistory_nonOwnerIsForbidden() throws Exception {
        mvc.perform(post("/logosdb/billing/key_budget_history/2001")
                .header("logos-key", "service-key-no-user")
                .contentType("application/json")
                .content("""
                    {"start_iso":"2020-01-01T00:00:00Z","end_iso":"2030-01-01T00:00:00Z"}
                    """))
           .andExpect(status().isForbidden());
    }
}