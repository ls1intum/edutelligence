package de.tum.cit.aet.logos.logoswebservice.websocket;

import java.util.Map;

import org.springframework.dao.DataAccessException;
import org.springframework.http.server.ServerHttpRequest;
import org.springframework.http.server.ServerHttpResponse;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.WebSocketHandler;
import org.springframework.web.socket.server.HandshakeInterceptor;

import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakClaimExtractor;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import de.tum.cit.aet.logos.logoswebservice.identity.service.KeycloakUserSyncService;

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
        if (!(authentication instanceof JwtAuthenticationToken jwtAuth)) return false;

        User user;
        try {
            user = syncService.syncIfStale(claimExtractor.extract(jwtAuth.getToken()));
        } catch (IllegalArgumentException | DataAccessException e) {
            return false;
        }
        if (!Boolean.TRUE.equals(user.getIsActive())) return false;

        attributes.put("logosKey", jwtAuth.getToken().getTokenValue());
        attributes.put("userId", user.getId());
        return true;
    }

    @Override
    public void afterHandshake(ServerHttpRequest request, ServerHttpResponse response,
                               WebSocketHandler wsHandler, Exception exception) {}
}
