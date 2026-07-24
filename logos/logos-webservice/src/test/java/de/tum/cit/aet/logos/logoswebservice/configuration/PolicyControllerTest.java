package de.tum.cit.aet.logos.logoswebservice.configuration;

import static org.hamcrest.Matchers.notNullValue;
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
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql", "/sql/seed-admin.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-admin.sql", "/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class PolicyControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void getPolicies_returnsPoliciesLinkedToKey() throws Exception {
        mvc.perform(post("/logosdb/get_policies")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$[0].id").value(8001))
           .andExpect(jsonPath("$[0].name").value("test-policy"))
           .andExpect(jsonPath("$[0].threshold_privacy").value("LOCAL"));
    }

    @Test
    void getPolicies_requiresAuth() throws Exception {
        mvc.perform(post("/logosdb/get_policies")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isUnauthorized());
    }

    @Test
    void addPolicy_logosAdminCanCreate() throws Exception {
        mvc.perform(post("/logosdb/add_policy")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("""
                    {"name":"p2","description":"d","threshold_privacy":"LOCAL",
                     "threshold_latency":0,"threshold_accuracy":0,"threshold_cost":0,
                     "threshold_quality":0,"priority":1,"topic":"t"}
                    """))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$['policy-id']", notNullValue()));
    }

    @Test
    void addPolicy_nonAdminIsForbidden() throws Exception {
        mvc.perform(post("/logosdb/add_policy")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("""
                    {"name":"p","description":"d","threshold_privacy":"LOCAL",
                     "threshold_latency":0,"threshold_accuracy":0,"threshold_cost":0,
                     "threshold_quality":0,"priority":1,"topic":"t"}
                    """))
           .andExpect(status().isForbidden());
    }

    @Test
    void updatePolicy_logosAdminCanUpdate() throws Exception {
        mvc.perform(post("/logosdb/update_policy")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("""
                    {"id":8001,"name":"updated","description":"d","threshold_privacy":"LOCAL",
                     "threshold_latency":1,"threshold_accuracy":2,"threshold_cost":3,
                     "threshold_quality":4,"priority":10,"topic":"t2"}
                    """))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Updated Policy"));
    }

    @Test
    void updatePolicy_nonAdminIsForbidden() throws Exception {
        mvc.perform(post("/logosdb/update_policy")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"id\":8001,\"name\":\"x\"}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void deletePolicy_logosAdminCanDelete() throws Exception {
        mvc.perform(post("/logosdb/delete_policy")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"id\":8001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Deleted Policy"));
    }

    @Test
    void deletePolicy_nonAdminIsForbidden() throws Exception {
        mvc.perform(post("/logosdb/delete_policy")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"id\":8001}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void getPolicy_keyOwnerCanFetch() throws Exception {
        mvc.perform(post("/logosdb/get_policy")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"policy_id\":8001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.id").value(8001));
    }
}
