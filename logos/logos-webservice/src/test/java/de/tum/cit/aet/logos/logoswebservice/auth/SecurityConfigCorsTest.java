package de.tum.cit.aet.logos.logoswebservice.auth;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.DefaultCorsProcessor;

/**
 * Preflight coverage for the inference CORS allowlist: a browser client must
 * be able to send either spelling of the per-request logging header.
 */
class SecurityConfigCorsTest {

    private CorsConfigurationSource source;
    private final DefaultCorsProcessor processor = new DefaultCorsProcessor();

    @BeforeEach
    void setUp() {
        source = new SecurityConfig().logosCorsConfigurationSource("https://app.example");
    }

    @ParameterizedTest
    @ValueSource(strings = {"logos-logging", "logos_logging"})
    void inferencePreflightAllowsLoggingHeaderSpellings(String header) throws IOException {
        for (String path : new String[] {"/v1/chat/completions", "/openai/v1/chat/completions", "/jobs"}) {
            MockHttpServletResponse response = preflight(path, header);
            assertThat(response.getStatus()).isEqualTo(200);
            assertThat(response.getHeader(HttpHeaders.ACCESS_CONTROL_ALLOW_HEADERS))
                .containsIgnoringCase(header);
        }
    }

    @Test
    void inferencePreflightRejectsDisallowedHeader() throws IOException {
        // Spring refuses the preflight when Access-Control-Request-Headers
        // names something outside the allowlist.
        MockHttpServletResponse response = preflight("/v1/chat/completions", "X-Secret-Header");
        assertThat(response.getStatus()).isEqualTo(403);
    }

    @Test
    void adminPreflightStillRefusesLoggingHeader() throws IOException {
        // Admin allowlist is tight; logos-logging is inference-only.
        MockHttpServletResponse response = preflight("/me", "logos-logging");
        assertThat(response.getStatus()).isEqualTo(403);
    }

    private MockHttpServletResponse preflight(String path, String requestHeader) throws IOException {
        MockHttpServletRequest request = new MockHttpServletRequest(HttpMethod.OPTIONS.name(), path);
        request.addHeader(HttpHeaders.ORIGIN, "https://app.example");
        request.addHeader(HttpHeaders.ACCESS_CONTROL_REQUEST_METHOD, "POST");
        request.addHeader(HttpHeaders.ACCESS_CONTROL_REQUEST_HEADERS, requestHeader);
        MockHttpServletResponse response = new MockHttpServletResponse();
        processor.processRequest(source.getCorsConfiguration(request), request, response);
        return response;
    }
}
