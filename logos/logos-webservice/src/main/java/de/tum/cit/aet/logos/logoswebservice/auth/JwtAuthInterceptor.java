package de.tum.cit.aet.logos.logoswebservice.auth;

import java.util.List;

import org.springframework.dao.DataAccessException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import de.tum.cit.aet.logos.logoswebservice.common.RequestTiming;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import de.tum.cit.aet.logos.logoswebservice.identity.service.KeycloakUserSyncService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

@Component
public class JwtAuthInterceptor implements HandlerInterceptor {

    private final KeycloakClaimExtractor claimExtractor;
    private final KeycloakUserSyncService syncService;

    public JwtAuthInterceptor(KeycloakClaimExtractor claimExtractor, KeycloakUserSyncService syncService) {
        this.claimExtractor = claimExtractor;
        this.syncService = syncService;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler)
            throws Exception {
        var authentication = SecurityContextHolder.getContext().getAuthentication();
        if (!(authentication instanceof JwtAuthenticationToken jwtAuth)) {
            response.sendError(401, "Missing bearer token");
            return false;
        }

        long start = System.nanoTime();
        KeycloakClaims claims = claimExtractor.extract(jwtAuth.getToken());
        User user;
        boolean synced = false;
        try {
            var fresh = syncService.findIfFresh(claims);
            if (fresh.isPresent()) {
                user = fresh.get();
            } else {
                synced = true;
                user = syncService.syncFromClaims(claims);
            }
        } catch (IllegalArgumentException e) {
            response.sendError(401, "Invalid token subject");
            return false;
        } catch (DataAccessException e) {
            response.sendError(503, "User provisioning temporarily unavailable");
            return false;
        } finally {
            RequestTiming.recordAuth(System.nanoTime() - start, synced);
        }

        if (!user.isActive()) {
            response.sendError(403, "User is deactivated");
            return false;
        }

        request.setAttribute("authContext", new AuthContext(user.getId(), user.getRole()));
        SecurityContextHolder.getContext().setAuthentication(
            new UsernamePasswordAuthenticationToken(user.getUsername(), null,
                List.of(new SimpleGrantedAuthority(user.getRole()))));
        return true;
    }
}
