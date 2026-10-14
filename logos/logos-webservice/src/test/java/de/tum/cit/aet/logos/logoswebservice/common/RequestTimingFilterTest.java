package de.tum.cit.aet.logos.logoswebservice.common;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.jwt;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestContainersConfig.class)
@ExtendWith(OutputCaptureExtension.class)
@TestPropertySource(properties = {
        "spring.liquibase.enabled=true",
        "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml",
        "logos.auth.sync-debounce-minutes=5"
})
@Sql(scripts = "/sql/seed-identity.sql", executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = "/sql/cleanup-identity.sql", executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class RequestTimingFilterTest {

    private static final String NEW_SUBJECT = "44444444-4444-4444-4444-444444444444";

    @Autowired MockMvc mvc;
    @Autowired UserRepository userRepository;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void unsyncedUser_logsSyncPhases_thenFreshUserSkipsSync(CapturedOutput output) throws Exception {
        for (int i = 0; i < 2; i++) {
            mvc.perform(get("/me").with(jwt().jwt(j -> j.subject(NEW_SUBJECT)
                    .claim("preferred_username", "fresh.user").claim("email", "fresh@tum.de"))))
                .andExpect(status().isOk());
        }
        userRepository.findByKeycloakId(UUID.fromString(NEW_SUBJECT)).ifPresent(userRepository::delete);

        var lines = output.getOut().lines().filter(l -> l.contains("request GET /me ")).toList();
        assertThat(lines).hasSize(2);
        assertThat(lines.get(0))
            .contains("route=/me", "status=200", "sync=yes", "syncUserMs=", "syncLockMs=", "syncTeams=", "handlerMs=")
            .containsPattern("user=\\d+");
        assertThat(lines.get(1)).contains("sync=no").doesNotContain("syncLockMs=");
    }

    @Test
    void unauthenticatedRequest_isLoggedWithItsStatus(CapturedOutput output) throws Exception {
        mvc.perform(get("/me")).andExpect(status().isUnauthorized());

        assertThat(output.getOut()).containsPattern("request GET /me .*status=401 .*authMs=- .*handlerMs=- .*user=-");
    }
}
