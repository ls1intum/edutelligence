package de.tum.cit.aet.logos.logoswebservice.auth;

import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import de.tum.cit.aet.logos.logoswebservice.identity.service.KeycloakUserSyncService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

@Component
public class JwtAuthInterceptor implements HandlerInterceptor {

    private static final Logger log = LoggerFactory.getLogger(JwtAuthInterceptor.class);

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
        try {
            user = syncService.findIfFresh(claims)
                .orElseGet(() -> syncService.syncFromClaims(claims));
        } catch (IllegalArgumentException e) {
            response.sendError(401, "Invalid token subject");
            return false;
        } catch (DataAccessException e) {
            response.sendError(503, "User provisioning temporarily unavailable");
            return false;
        } finally {
            // Temporary instrumentation to localize prod-only /me and /me/keys
            // slowness reports: isolates auth+sync time from the rest of the
            // request (routing, controller, serialization).
            long elapsedMs = (System.nanoTime() - start) / 1_000_000;
            log.info("auth sync took {}ms for subject {} on {} {}",
                elapsedMs, claims.keycloakId(), request.getMethod(), request.getRequestURI());
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
