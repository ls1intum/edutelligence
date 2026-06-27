package de.tum.cit.aet.logos.logoswebservice.auth;

import java.time.Instant;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.jwt;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;

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
@Sql(scripts = "/sql/seed-identity.sql", executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = "/sql/cleanup-identity.sql", executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class JwtAuthInterceptorTest {

    @Autowired MockMvc mvc;
    @Autowired UserRepository userRepository;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void noToken_returns401() throws Exception {
        mvc.perform(get("/me")).andExpect(status().isUnauthorized());
    }

    @Test
    void unknownSubject_isJitProvisioned() throws Exception {
        String sub = "44444444-4444-4444-4444-444444444444";
        mvc.perform(get("/me").with(jwt().jwt(j -> j.subject(sub)
                .claim("preferred_username", "fresh.user")
                .claim("given_name", "Fresh").claim("family_name", "User")
                .claim("email", "fresh@tum.de"))))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.username").value("fresh.user"))
            .andExpect(jsonPath("$.role").value("app_developer"));

        var created = userRepository.findByKeycloakId(UUID.fromString(sub));
        assertThat(created).isPresent();
        userRepository.delete(created.get());
    }

    @Test
    void deactivatedUser_returns403() throws Exception {
        var user = userRepository.findById(1001).orElseThrow();
        user.setActive(false);
        userRepository.save(user);

        Instant oldIat = user.getLastSyncedAt().minusSeconds(120);
        mvc.perform(get("/me").with(jwt().jwt(j -> j
                .subject("00000000-0000-0000-0000-000000001001")
                .claim("preferred_username", "testuser")
                .issuedAt(oldIat))))
            .andExpect(status().isForbidden());
    }

    @Test
    void reenabledUser_freshTokenAfterDeactivation_isAllowed() throws Exception {
        var user = userRepository.findById(1001).orElseThrow();
        user.setActive(false);
        userRepository.save(user);

        Instant freshIat = user.getLastSyncedAt().plusSeconds(1);
        mvc.perform(get("/me").with(jwt().jwt(j -> j
                .subject("00000000-0000-0000-0000-000000001001")
                .claim("given_name", "Test")
                .claim("family_name", "User")
                .claim("email", "test@test.com")
                .claim("preferred_username", "testuser")
                .issuedAt(freshIat))))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.role").value("app_developer"));
    }

    @Test
    void nonUuidSubject_returns401() throws Exception {
        mvc.perform(get("/me").with(jwt().jwt(j -> j.subject("not-a-uuid"))))
            .andExpect(status().isUnauthorized());
    }
}
