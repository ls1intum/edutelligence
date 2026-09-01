package de.tum.cit.aet.logos.logoswebservice.configuration;

import java.time.Duration;
import java.time.Instant;

import com.jayway.jsonpath.JsonPath;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.context.jdbc.SqlMergeMode;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;
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
@Sql(scripts = {"/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class ModelControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void getModels_logosAdminReturnsAllModels() throws Exception {
        mvc.perform(post("/logosdb/get_models")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$[0].id").exists())
           .andExpect(jsonPath("$[0].name").exists());
    }

    @Test
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    @Sql(statements = {
        "INSERT INTO team_model_permissions (team_id, model_id) VALUES (2001, 5001)",
        "INSERT INTO team_provider_permissions (team_id, provider_id) VALUES (2001, 6001)"
    }, executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    void getModels_appAdminReturnsOnlyTeamAssignedModels() throws Exception {
        mvc.perform(post("/logosdb/get_models")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$.length()").value(1))
           .andExpect(jsonPath("$[0].id").value(5001))
           .andExpect(jsonPath("$[0].name").value("gpt-4"));
    }

    @Test
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    @Sql(statements = """
        INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                               timestamp_request, timestamp_forwarding, timestamp_response)
        VALUES
          (9501, 'req-last-used-old', 3001, 5001, 6001, 'success',
           NOW() - INTERVAL '31 days', NOW() - INTERVAL '31 days', NOW() - INTERVAL '31 days'),
          (9502, 'req-last-used-new', 3001, 5001, 6001, 'error',
           NOW() - INTERVAL '2 hours', NOW() - INTERVAL '2 hours', NOW() - INTERVAL '1 hour');
        INSERT INTO team_model_permissions (team_id, model_id) VALUES (2001, 5001);
        INSERT INTO team_provider_permissions (team_id, provider_id) VALUES (2001, 6001);
        """, executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    @Sql(statements = {
        "DELETE FROM log_entry WHERE id IN (9501, 9502)",
        "DELETE FROM team_model_permissions WHERE team_id = 2001 AND model_id = 5001",
        "DELETE FROM team_provider_permissions WHERE team_id = 2001 AND provider_id = 6001"
    }, executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
    void getModels_exposesLastUsedAtToLogosAdminsOnly() throws Exception {
        String body = mvc.perform(post("/logosdb/get_models")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andReturn().getResponse().getContentAsString();

        JsonNode models = new ObjectMapper().readTree(body);
        JsonNode gpt4 = null;
        JsonNode gpt35 = null;
        for (JsonNode model : models) {
            if (model.get("id").asInt() == 5001) gpt4 = model;
            if (model.get("id").asInt() == 5002) gpt35 = model;
        }

        assertThat(gpt4).isNotNull();
        assertThat(gpt35).isNotNull();
        // The newest request wins — the 2h-old row, not the 31d-old one — and an
        // errored request still counts as usage.
        assertThat(gpt4.get("last_used_at").isNull()).isFalse();
        Instant lastUsed = Instant.parse(gpt4.get("last_used_at").asText());
        assertThat(Duration.between(lastUsed, Instant.now()).abs()).isLessThan(Duration.ofHours(3));
        // A model without any log entry was never used.
        assertThat(gpt35.get("last_used_at").isNull()).isTrue();

        // The field is filtered server-side: non-admins never receive it, even
        // though the endpoint itself is open to all authenticated users.
        mvc.perform(post("/logosdb/get_models")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(1))
           .andExpect(jsonPath("$[0].id").value(5001))
           .andExpect(jsonPath("$[0].last_used_at").doesNotExist());
    }

    @Test
    void getModels_requiresAuth() throws Exception {
        mvc.perform(post("/logosdb/get_models")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isUnauthorized());
    }

    @Test
    void addModel_requiresLogosAdmin() throws Exception {
        mvc.perform(post("/logosdb/add_model")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"name\":\"new-model\"}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void addModel_logosAdminCanCreate() throws Exception {
        mvc.perform(post("/logosdb/add_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"name\":\"test-model\",\"tags\":\"\",\"description\":\"\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.model_id").isNumber());
    }

    @Test
    void addModel_modelResponseExposesNoParallelField() throws Exception {
        // models.parallel has been dropped from the schema; parallel capacity
        // is derived by the orchestrator from the worker's live lane signals.
        MvcResult addResult = mvc.perform(post("/logosdb/add_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"name\":\"no-parallel-model\"}"))
           .andExpect(status().isOk())
           .andReturn();
        int modelId = JsonPath.read(addResult.getResponse().getContentAsString(), "$.model_id");

        mvc.perform(post("/logosdb/get_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"id\":" + modelId + "}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.id").value(modelId))
           .andExpect(jsonPath("$.parallel").doesNotExist());

        mvc.perform(post("/logosdb/get_models")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$[?(@.id == %d)].parallel".formatted(modelId)).doesNotExist());
    }

    @Test
    void updateModelInfo_updatesNameField() throws Exception {
        mvc.perform(post("/logosdb/update_model_info")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5001,\"name\":\"updated-name\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Model updated"));
    }

    @Test
    void deleteModel_requiresLogosAdmin() throws Exception {
        mvc.perform(post("/logosdb/delete_model")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"id\":5001}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void deleteModel_logosAdminCanDelete() throws Exception {
        mvc.perform(post("/logosdb/delete_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"id\":5001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Deleted Model"));
    }

    @Test
    void getModel_returnsCorrectFields() throws Exception {
        mvc.perform(post("/logosdb/get_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"id\":5001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.id").value(5001))
           .andExpect(jsonPath("$.name").value("gpt-4"));
    }

    @Test
    void getGeneralModelStats_returnsCount() throws Exception {
        mvc.perform(post("/logosdb/get_general_model_stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.totalModels").isNumber());
    }

    @Test
    void updateModel_logosAdminCanGiveFeedback() throws Exception {
        mvc.perform(post("/logosdb/update_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"id\":5001,\"category\":\"accuracy\",\"value\":2}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Updated Model"));
    }

    @Test
    void updateModel_invalidCategoryReturns400() throws Exception {
        mvc.perform(post("/logosdb/update_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"id\":5001,\"category\":\"bogus\",\"value\":1}"))
           .andExpect(status().isBadRequest());
    }

    @Test
    void updateModel_nonAdminIsForbidden() throws Exception {
        mvc.perform(post("/logosdb/update_model")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"id\":5001,\"category\":\"accuracy\",\"value\":1}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void addModel_withAliasesExposesThemInModelAndList() throws Exception {
        MvcResult addResult = mvc.perform(post("/logosdb/add_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"name\":\"alias-model\",\"aliases\":[\"local-most-powerful\",\"local-fast\"]}"))
           .andExpect(status().isOk())
           .andReturn();
        int modelId = JsonPath.read(addResult.getResponse().getContentAsString(), "$.model_id");

        // The single-model endpoint returns the sorted alias list...
        mvc.perform(post("/logosdb/get_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"id\":" + modelId + "}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.aliases.length()").value(2))
           .andExpect(jsonPath("$.aliases[0]").value("local-fast"))
           .andExpect(jsonPath("$.aliases[1]").value("local-most-powerful"));

        // ...the model list the comma-joined form, and a model without
        // aliases gets no value at all.
        mvc.perform(post("/logosdb/get_models")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$[?(@.id == %d)].aliases".formatted(modelId))
                .value("local-fast, local-most-powerful"))
           // A model without aliases has no alias value (null or absent).
           .andExpect(jsonPath("$[?(@.id == 5001)].aliases[0]").doesNotExist());
    }

    @Test
    void updateModelInfo_replacesAndClearsAliases() throws Exception {
        mvc.perform(post("/logosdb/update_model_info")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5001,\"aliases\":[\"local-gpt\"]}"))
           .andExpect(status().isOk());
        mvc.perform(post("/logosdb/get_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"id\":5001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.aliases.length()").value(1))
           .andExpect(jsonPath("$.aliases[0]").value("local-gpt"));

        // Re-adding the same alias with different capitalization keeps a
        // single case-insensitively unique entry.
        mvc.perform(post("/logosdb/update_model_info")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5001,\"aliases\":[\"Local-GPT\"]}"))
           .andExpect(status().isOk());
        mvc.perform(post("/logosdb/get_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"id\":5001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.aliases.length()").value(1));

        // An empty list removes all aliases.
        mvc.perform(post("/logosdb/update_model_info")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5001,\"aliases\":[]}"))
           .andExpect(status().isOk());
        mvc.perform(post("/logosdb/get_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"id\":5001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.aliases.length()").value(0));
    }

    @Test
    void updateModelInfo_aliasCollidingWithModelNameIsRejected() throws Exception {
        // Model 5001 is named 'gpt-4'; an alias differing only in
        // capitalization would be ambiguous to resolve.
        mvc.perform(post("/logosdb/update_model_info")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5002,\"aliases\":[\"GPT-4\"]}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").exists());
    }

    @Test
    void addModel_aliasAlreadyAssignedToAnotherModelIsRejected() throws Exception {
        mvc.perform(post("/logosdb/update_model_info")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5001,\"aliases\":[\"shared-alias\"]}"))
           .andExpect(status().isOk());

        mvc.perform(post("/logosdb/add_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"name\":\"alias-conflict\",\"aliases\":[\"shared-alias\"]}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").exists());
    }

    @Test
    void addModel_nameCollidingWithExistingAliasIsRejected() throws Exception {
        // Model 5001 owns the alias 'local-gpt'. Creating a model whose NAME is
        // that alias would shadow it, because the resolver matches a canonical
        // name before it ever consults aliases — so the create path must reject
        // it (the mirror of the alias-collides-with-name check).
        mvc.perform(post("/logosdb/update_model_info")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5001,\"aliases\":[\"local-gpt\"]}"))
           .andExpect(status().isOk());

        mvc.perform(post("/logosdb/add_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"name\":\"local-gpt\"}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").exists());
    }

    @Test
    void updateModelInfo_renameToExistingAliasIsRejected() throws Exception {
        // Model 5001 owns the alias 'local-gpt'. Renaming model 5002 to that
        // name would silently steal every request that used the alias while the
        // alias row still points at model 5001 — the rename path is the easy
        // one to miss, so it is covered explicitly.
        mvc.perform(post("/logosdb/update_model_info")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5001,\"aliases\":[\"local-gpt\"]}"))
           .andExpect(status().isOk());

        mvc.perform(post("/logosdb/update_model_info")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5002,\"name\":\"local-gpt\"}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").exists());
    }

    @Test
    void addModel_nameCollidingWithExistingAliasIsCaseInsensitive() throws Exception {
        // The collision rule is case-insensitive, matching the alias-side check:
        // a name that differs only in capitalization from an existing alias is
        // still rejected.
        mvc.perform(post("/logosdb/update_model_info")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5001,\"aliases\":[\"local-gpt\"]}"))
           .andExpect(status().isOk());

        mvc.perform(post("/logosdb/add_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"name\":\"LOCAL-GPT\"}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").exists());
    }

    @Test
    void addModel_nameCollidingWithExistingModelNameIsRejected() throws Exception {
        // Model 5001 is named 'gpt-4'. Creating a model whose name differs only
        // in case would leave two rows for one identifier; the resolver treats
        // such rows as ambiguous and 404s every request for either spelling, so
        // the create path must reject the duplicate.
        mvc.perform(post("/logosdb/add_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"name\":\"GPT-4\"}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").exists());
    }

    @Test
    void updateModelInfo_renameToExistingModelNameIsRejected() throws Exception {
        // Model 5001 is named 'gpt-4'. Renaming model 5002 to 'GPT-4' would
        // create the same duplicate — the rename path is covered explicitly,
        // mirroring the alias-collision tests above.
        mvc.perform(post("/logosdb/update_model_info")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5002,\"name\":\"GPT-4\"}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").exists());
    }

    @Test
    void updateModelInfo_ownNameInDifferentCaseIsAllowed() throws Exception {
        // The uniqueness check exempts the model being updated: submitting the
        // model's own name — even re-cased — must not read as a self-collision.
        mvc.perform(post("/logosdb/update_model_info")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5001,\"name\":\"GPT-4\"}"))
           .andExpect(status().isOk());
    }
}
