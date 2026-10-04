package de.tum.cit.aet.logos.logoswebservice.websocket;

import java.util.Map;

import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.server.ServerHttpRequest;
import org.springframework.http.server.ServerHttpResponse;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.WebSocketHandler;
import org.springframework.web.socket.server.HandshakeInterceptor;

import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakClaimExtractor;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import de.tum.cit.aet.logos.logoswebservice.identity.service.KeycloakUserSyncService;

/**
 * Handshake guard for the stats websockets.
 *
 * <p>Both endpoints it protects stream system-wide operational data — the
 * request feed carries every requester's full name, team and cloud cost, with no
 * per-user scoping to fall back on. So being authenticated is not enough: the
 * handshake requires {@code LOGOS_ADMIN}, matching
 * {@code POST /logosdb/latest_requests}, which serves the same rows over REST.
 * The statistics page is the only consumer and is already admin-gated in the
 * router; this makes the same rule hold server-side.
 */
@Component
public class WebSocketAuthInterceptor implements HandshakeInterceptor {

    private final KeycloakClaimExtractor claimExtractor;
    private final KeycloakUserSyncService syncService;

    public WebSocketAuthInterceptor(KeycloakClaimExtractor claimExtractor, KeycloakUserSyncService syncService) {
        this.claimExtractor = claimExtractor;
        this.syncService = syncService;
    }

    @Override
    public boolean beforeHandshake(ServerHttpRequest request, ServerHttpResponse response,
                                   WebSocketHandler wsHandler, Map<String, Object> attributes) {
        var authentication = SecurityContextHolder.getContext().getAuthentication();
        if (!(authentication instanceof JwtAuthenticationToken jwtAuth)) {
            response.setStatusCode(HttpStatus.UNAUTHORIZED);
            return false;
        }

        User user;
        try {
            user = syncService.syncIfStale(claimExtractor.extract(jwtAuth.getToken()));
        } catch (IllegalArgumentException | DataAccessException e) {
            response.setStatusCode(HttpStatus.UNAUTHORIZED);
            return false;
        }
        if (!user.isActive() || !Role.LOGOS_ADMIN.matches(user.getRole())) {
            response.setStatusCode(HttpStatus.FORBIDDEN);
            return false;
        }

        attributes.put("logosKey", jwtAuth.getToken().getTokenValue());
        attributes.put("userId", user.getId());
        return true;
    }

    @Override
    public void afterHandshake(ServerHttpRequest request, ServerHttpResponse response,
                               WebSocketHandler wsHandler, Exception exception) {}
}
