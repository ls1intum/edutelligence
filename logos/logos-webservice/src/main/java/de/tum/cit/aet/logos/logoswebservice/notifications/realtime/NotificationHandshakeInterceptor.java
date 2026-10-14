package de.tum.cit.aet.logos.logoswebservice.notifications.realtime;

import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

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
import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.service.KeycloakUserSyncService;

/**
 * Handshake guard for {@code /ws/notifications}. Unlike the stats sockets,
 * every active user may connect: each socket only ever receives the
 * notifications addressed to its own user, role, or teams.
 */
@Component
public class NotificationHandshakeInterceptor implements HandshakeInterceptor {

    static final String USER_ID = "notificationUserId";
    static final String ROLE = "notificationRole";
    static final String TEAM_IDS = "notificationTeamIds";

    private final KeycloakClaimExtractor claimExtractor;
    private final KeycloakUserSyncService syncService;
    private final TeamMemberRepository teamMembers;

    public NotificationHandshakeInterceptor(KeycloakClaimExtractor claimExtractor,
                                            KeycloakUserSyncService syncService,
                                            TeamMemberRepository teamMembers) {
        this.claimExtractor = claimExtractor;
        this.syncService = syncService;
        this.teamMembers = teamMembers;
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
        if (!user.isActive()) {
            response.setStatusCode(HttpStatus.FORBIDDEN);
            return false;
        }
        Set<Integer> teamIds = teamMembers.findById_UserId(user.getId()).stream()
            .map(member -> member.getId().getTeamId())
            .collect(Collectors.toUnmodifiableSet());
        attributes.put(USER_ID, user.getId());
        attributes.put(ROLE, user.getRole());
        attributes.put(TEAM_IDS, teamIds);
        return true;
    }

    @Override
    public void afterHandshake(ServerHttpRequest request, ServerHttpResponse response,
                               WebSocketHandler wsHandler, Exception exception) {}
}
