package de.tum.cit.aet.logos.logoswebservice.auth;

import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.MediaType;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.web.client.RestClient;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import dasniko.testcontainers.keycloak.KeycloakContainer;
import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestContainersConfig.class)
@Testcontainers
@TestPropertySource(properties = {
        "spring.liquibase.enabled=true",
        "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml",
        "logos.auth.roles.logos-admin=itg-admin",
        "logos.auth.roles.app-admin=chair-member"
})
class KeycloakEndToEndTest {

    @Container
    static KeycloakContainer keycloak = new KeycloakContainer("quay.io/keycloak/keycloak:26.4")
            .withRealmImportFile("/keycloak/tum-realm.json");

    @DynamicPropertySource
    static void keycloakProps(DynamicPropertyRegistry registry) {
        registry.add("spring.security.oauth2.resourceserver.jwt.issuer-uri",
                () -> keycloak.getAuthServerUrl() + "/realms/tum");
        registry.add("spring.security.oauth2.resourceserver.jwt.jwk-set-uri",
                () -> keycloak.getAuthServerUrl() + "/realms/tum/protocol/openid-connect/certs");
    }

    @Autowired MockMvc mvc;
    @Autowired UserRepository userRepository;

    private String passwordToken(String username) {
        var form = new LinkedMultiValueMap<String, String>();
        form.add("grant_type", "password");
        form.add("client_id", "logos");
        form.add("username", username);
        form.add("password", "password");
        Map<String, Object> response = RestClient.create().post()
                .uri(keycloak.getAuthServerUrl() + "/realms/tum/protocol/openid-connect/token")
                .contentType(MediaType.APPLICATION_FORM_URLENCODED)
                .body(form)
                .retrieve()
                .body(new ParameterizedTypeReference<>() {});
        return (String) response.get("access_token");
    }

    @Test
    void realKeycloakToken_jitProvisionsAdminWithPersonalKey() throws Exception {
        String token = passwordToken("tobias.wasner");

        mvc.perform(get("/me").header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.username").value("tobias.wasner"))
                .andExpect(jsonPath("$.role").value("logos_admin"));

        assertThat(userRepository.findByUsername("tobias.wasner")).isPresent();


        mvc.perform(get("/me").header("logos-key", token))
                .andExpect(status().isOk());
    }

    @Test
    void userWithoutMappedRole_isAppDeveloper() throws Exception {
        String token = passwordToken("henriette.huhn");

        mvc.perform(get("/me").header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.role").value("app_developer"));
    }
}
