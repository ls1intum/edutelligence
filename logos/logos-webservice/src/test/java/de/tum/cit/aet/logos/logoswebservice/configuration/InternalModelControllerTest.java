package de.tum.cit.aet.logos.logoswebservice.configuration;

import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelCapabilitiesUpdaterService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.PriceUpdaterService;

/**
 * The orchestrator announces newly discovered models with the internal secret
 * as a Bearer token — not a JWT. This exercises the whole filter chain:
 * without the LogosBearerTokenResolver bypass the resource-server filter would
 * reject the secret as an undecodable JWT, and without the WebConfig
 * interceptor exclusion the JwtAuthInterceptor would reject the missing JWT
 * authentication — both with a 401 before the controller's own validation.
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
    "logos.orchestrator.internal-secret=test-internal-secret"
})
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class InternalModelControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;
    // Mocked so the refreshes do not reach the live litellm catalog in tests.
    @MockitoBean PriceUpdaterService priceUpdaterService;
    @MockitoBean ModelCapabilitiesUpdaterService modelCapabilitiesUpdaterService;

    @Test
    void internalSecretTriggersPriceAndCapabilityRefresh() throws Exception {
        mvc.perform(post("/internal/models_discovered")
                .header("Authorization", "Bearer test-internal-secret")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"model_ids\": [5002]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.status").value("accepted"));

        verify(priceUpdaterService).updatePricesForModelAsync(5002, "gpt-3.5");
        verify(modelCapabilitiesUpdaterService).updateCapabilitiesForModelAsync(5002, "gpt-3.5");
    }

    @Test
    void wrongSecretIsRejected() throws Exception {
        mvc.perform(post("/internal/models_discovered")
                .header("Authorization", "Bearer wrong-secret")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"model_ids\": [5002]}"))
           .andExpect(status().isUnauthorized());

        verifyNoInteractions(priceUpdaterService, modelCapabilitiesUpdaterService);
    }

    @Test
    void missingAuthorizationIsRejected() throws Exception {
        mvc.perform(post("/internal/models_discovered")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"model_ids\": [5002]}"))
           .andExpect(status().isUnauthorized());

        verifyNoInteractions(priceUpdaterService, modelCapabilitiesUpdaterService);
    }
}
