package de.tum.cit.aet.logos.logoswebservice.websocket;

import java.util.HashMap;
import java.util.Map;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.http.HttpStatus;
import org.springframework.http.server.ServletServerHttpRequest;
import org.springframework.http.server.ServletServerHttpResponse;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakClaimExtractor;
import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakClaims;
import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakProperties;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import de.tum.cit.aet.logos.logoswebservice.identity.service.KeycloakUserSyncService;

class WebSocketAuthInterceptorTest {

    private final KeycloakUserSyncService syncService = mock(KeycloakUserSyncService.class);
    private final KeycloakClaimExtractor extractor = new KeycloakClaimExtractor(
        new KeycloakProperties("logos",
            new KeycloakProperties.Roles(java.util.List.of(), java.util.List.of()), 5,
            new KeycloakProperties.Sync(false, "", "", "tum", "logos-sync", ""),
            java.util.List.of("-dev"), "logos", false));
    private final WebSocketAuthInterceptor interceptor = new WebSocketAuthInterceptor(extractor, syncService);

    @AfterEach
    void clearContext() {
        SecurityContextHolder.clearContext();
    }

    private void authenticate(boolean active, String role) {
        Jwt jwt = Jwt.withTokenValue("the-token").header("alg", "RS256")
            .subject("11111111-1111-1111-1111-111111111111")
            .claim("preferred_username", "alice").build();
        SecurityContextHolder.getContext().setAuthentication(new JwtAuthenticationToken(jwt));
        User user = new User();
        user.setActive(active);
        user.setRole(role);
        when(syncService.syncIfStale(any(KeycloakClaims.class))).thenReturn(user);
    }

    private HandshakeResult handshake() {
        MockHttpServletResponse servletResponse = new MockHttpServletResponse();
        Map<String, Object> attributes = new HashMap<>();
        boolean accepted = interceptor.beforeHandshake(
            new ServletServerHttpRequest(new MockHttpServletRequest()),
            new ServletServerHttpResponse(servletResponse),
            null, attributes);
        return new HandshakeResult(accepted, servletResponse.getStatus(), attributes);
    }

    private record HandshakeResult(boolean accepted, int status, Map<String, Object> attributes) {}

    @Test
    void logosAdmin_passesAndExposesAttributes() {
        authenticate(true, Role.Names.LOGOS_ADMIN);
        HandshakeResult result = handshake();
        assertThat(result.accepted()).isTrue();
        assertThat(result.attributes()).containsKey("logosKey");
    }

    @Test
    void noAuthentication_rejects() {
        HandshakeResult result = handshake();
        assertThat(result.accepted()).isFalse();
        assertThat(result.status()).isEqualTo(HttpStatus.UNAUTHORIZED.value());
    }

    @Test
    void deactivatedUser_rejects() {
        authenticate(false, Role.Names.LOGOS_ADMIN);
        HandshakeResult result = handshake();
        assertThat(result.accepted()).isFalse();
        assertThat(result.status()).isEqualTo(HttpStatus.FORBIDDEN.value());
    }

    @Test
    void nonAdminUser_rejects() {
        // The stats sockets stream the system-wide request feed — every
        // requester's full name, team and cloud cost — so authenticated is not
        // enough. Same rule as POST /logosdb/latest_requests, which serves the
        // very same rows over REST.
        authenticate(true, Role.Names.APP_DEVELOPER);
        HandshakeResult result = handshake();
        assertThat(result.accepted()).isFalse();
        assertThat(result.status()).isEqualTo(HttpStatus.FORBIDDEN.value());
        assertThat(result.attributes()).doesNotContainKey("logosKey");
    }

    @Test
    void userWithoutAnyRole_rejects() {
        authenticate(true, null);
        HandshakeResult result = handshake();
        assertThat(result.accepted()).isFalse();
        assertThat(result.status()).isEqualTo(HttpStatus.FORBIDDEN.value());
    }

    @Test
    void failedUserSync_rejectsAsUnauthenticated() {
        // The identity could not be established at all, so this is 401 rather
        // than the 403 that a known user lacking the role gets.
        Jwt jwt = Jwt.withTokenValue("the-token").header("alg", "RS256")
            .subject("11111111-1111-1111-1111-111111111111")
            .claim("preferred_username", "alice").build();
        SecurityContextHolder.getContext().setAuthentication(new JwtAuthenticationToken(jwt));
        when(syncService.syncIfStale(any(KeycloakClaims.class)))
            .thenThrow(new DataAccessResourceFailureException("directory unreachable"));

        HandshakeResult result = handshake();
        assertThat(result.accepted()).isFalse();
        assertThat(result.status()).isEqualTo(HttpStatus.UNAUTHORIZED.value());
        assertThat(result.attributes()).doesNotContainKey("logosKey");
    }
}
