package de.tum.cit.aet.logos.logoswebservice.websocket;

import java.util.HashMap;
import java.util.Map;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
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

    private void authenticate(boolean active) {
        Jwt jwt = Jwt.withTokenValue("the-token").header("alg", "RS256")
            .subject("11111111-1111-1111-1111-111111111111")
            .claim("preferred_username", "alice").build();
        SecurityContextHolder.getContext().setAuthentication(new JwtAuthenticationToken(jwt));
        User user = new User();
        user.setActive(active);
        when(syncService.syncIfStale(any(KeycloakClaims.class))).thenReturn(user);
    }

    @Test
    void authenticatedActiveUser_passesAndExposesAttributes() {
        authenticate(true);
        Map<String, Object> attributes = new HashMap<>();
        boolean result = interceptor.beforeHandshake(
            new ServletServerHttpRequest(new MockHttpServletRequest()),
            new ServletServerHttpResponse(new MockHttpServletResponse()),
            null, attributes);
        assertThat(result).isTrue();
        assertThat(attributes).containsKey("logosKey");
    }

    @Test
    void noAuthentication_rejects() {
        boolean result = interceptor.beforeHandshake(
            new ServletServerHttpRequest(new MockHttpServletRequest()),
            new ServletServerHttpResponse(new MockHttpServletResponse()),
            null, new HashMap<>());
        assertThat(result).isFalse();
    }

    @Test
    void deactivatedUser_rejects() {
        authenticate(false);
        boolean result = interceptor.beforeHandshake(
            new ServletServerHttpRequest(new MockHttpServletRequest()),
            new ServletServerHttpResponse(new MockHttpServletResponse()),
            null, new HashMap<>());
        assertThat(result).isFalse();
    }
}
