package de.tum.cit.aet.logos.logoswebservice.configuration;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
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
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-requested-models.sql", "/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class ModelRequestControllerTest {

    @Autowired MockMvc mvc;
    @Autowired JdbcTemplate jdbc;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void getModelRequests_emptyReturnsEmptyArray() throws Exception {
        mvc.perform(post("/logosdb/get_model_requests")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void vote_createsModelAndCountsOne() throws Exception {
        mvc.perform(post("/logosdb/add_model_request")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"name\": \"gpt-5\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.name").value("gpt-5"))
           .andExpect(jsonPath("$.request_count").value(1))
           .andExpect(jsonPath("$.has_voted").value(true))
           .andExpect(jsonPath("$.id").isNumber());
    }

    @Test
    void vote_isOnePerUserPerModel() throws Exception {
        mvc.perform(post("/logosdb/add_model_request")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"name\": \"gpt-5\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.request_count").value(1));

        // A second vote by the same user for the same model is a no-op: everyone
        // gets exactly one vote, so the count must not rise to two.
        mvc.perform(post("/logosdb/add_model_request")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"name\": \"gpt-5\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.request_count").value(1));
    }

    @Test
    void vote_secondUserIncrementsTheCount() throws Exception {
        mvc.perform(post("/logosdb/add_model_request")
                .with(TestJwt.testUser())
                .contentType("application/json").content("{\"name\": \"gpt-5\"}"))
           .andExpect(status().isOk());
        mvc.perform(post("/logosdb/add_model_request")
                .with(TestJwt.adminUser())
                .contentType("application/json").content("{\"name\": \"gpt-5\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.request_count").value(2));
    }

    @Test
    void vote_rejectsAModelThatIsAlreadyServed() throws Exception {
        // "gpt-4" is seeded into the models table, so it is already available and
        // must not be requestable.
        mvc.perform(post("/logosdb/add_model_request")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"name\": \"gpt-4\"}"))
           .andExpect(status().isConflict())
           .andExpect(jsonPath("$.error").exists());
    }

    @Test
    void undo_takesTheVoteBackAndAllowsRevoting() throws Exception {
        mvc.perform(post("/logosdb/add_model_request")
                .with(TestJwt.testUser())
                .contentType("application/json").content("{\"name\": \"claude\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.request_count").value(1));

        // Undo: the (only) vote is removed, the model's registry row goes with it.
        mvc.perform(post("/logosdb/remove_model_request")
                .with(TestJwt.testUser())
                .contentType("application/json").content("{\"name\": \"claude\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.request_count").value(0))
           .andExpect(jsonPath("$.has_voted").value(false));

        mvc.perform(post("/logosdb/get_model_requests")
                .with(TestJwt.testUser())
                .contentType("application/json").content("{}"))
           .andExpect(jsonPath("$.length()").value(0));

        // Re-vote: the model is requestable again and counts one.
        mvc.perform(post("/logosdb/add_model_request")
                .with(TestJwt.testUser())
                .contentType("application/json").content("{\"name\": \"claude\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.request_count").value(1));
    }

    @Test
    void list_reportsHasVotedPerVoter() throws Exception {
        mvc.perform(post("/logosdb/add_model_request")
                .with(TestJwt.testUser())
                .contentType("application/json").content("{\"name\": \"llama\"}"))
           .andExpect(status().isOk());

        // The voter sees has_voted=true ...
        mvc.perform(post("/logosdb/get_model_requests")
                .with(TestJwt.testUser())
                .contentType("application/json").content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(1))
           .andExpect(jsonPath("$[0].name").value("llama"))
           .andExpect(jsonPath("$[0].request_count").value(1))
           .andExpect(jsonPath("$[0].has_voted").value(true));

        // ... a user who did not vote sees has_voted=false for the same model.
        mvc.perform(post("/logosdb/get_model_requests")
                .with(TestJwt.adminUser())
                .contentType("application/json").content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(1))
           .andExpect(jsonPath("$[0].name").value("llama"))
           .andExpect(jsonPath("$[0].request_count").value(1))
           .andExpect(jsonPath("$[0].has_voted").value(false));
    }

    @Test
    void list_excludesModelsThatBecameServed() throws Exception {
        // First request "gpt-5" (not yet served) ...
        mvc.perform(post("/logosdb/add_model_request")
                .with(TestJwt.testUser())
                .contentType("application/json").content("{\"name\": \"gpt-5\"}"))
           .andExpect(status().isOk());
        mvc.perform(post("/logosdb/get_model_requests")
                .with(TestJwt.testUser())
                .contentType("application/json").content("{}"))
           .andExpect(jsonPath("$.length()").value(1));

        // ... then an admin adds it to the models table (simulated directly).
        jdbc.update("INSERT INTO models (id, name) VALUES (5099, 'gpt-5')");
        try {
            // It is served now, so it drops out of the requests list.
            mvc.perform(post("/logosdb/get_model_requests")
                    .with(TestJwt.testUser())
                    .contentType("application/json").content("{}"))
               .andExpect(status().isOk())
               .andExpect(jsonPath("$.length()").value(0));
        } finally {
            jdbc.update("DELETE FROM models WHERE id = 5099");
        }
    }

    @Test
    void list_ordersByVoteCountDescending() throws Exception {
        mvc.perform(post("/logosdb/add_model_request")
                .with(TestJwt.testUser())
                .contentType("application/json").content("{\"name\": \"alpha\"}"))
           .andExpect(status().isOk());
        mvc.perform(post("/logosdb/add_model_request")
                .with(TestJwt.adminUser())
                .contentType("application/json").content("{\"name\": \"alpha\"}"))
           .andExpect(status().isOk());
        mvc.perform(post("/logosdb/add_model_request")
                .with(TestJwt.testUser())
                .contentType("application/json").content("{\"name\": \"beta\"}"))
           .andExpect(status().isOk());

        mvc.perform(post("/logosdb/get_model_requests")
                .with(TestJwt.testUser())
                .contentType("application/json").content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(2))
           // "alpha" (2 votes) ranks above "beta" (1 vote).
           .andExpect(jsonPath("$[0].name").value("alpha"))
           .andExpect(jsonPath("$[0].request_count").value(2))
           .andExpect(jsonPath("$[1].name").value("beta"))
           .andExpect(jsonPath("$[1].request_count").value(1));
    }

    @Test
    void vote_blankNameIsBadRequest() throws Exception {
        mvc.perform(post("/logosdb/add_model_request")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"name\": \"   \"}"))
           .andExpect(status().isBadRequest());

        mvc.perform(post("/logosdb/add_model_request")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isBadRequest());
    }

    @Test
    void addModelRequest_withoutTokenIsUnauthorized() throws Exception {
        mvc.perform(post("/logosdb/add_model_request")
                .contentType("application/json")
                .content("{\"name\": \"gpt-5\"}"))
           .andExpect(status().isUnauthorized());
    }
}
