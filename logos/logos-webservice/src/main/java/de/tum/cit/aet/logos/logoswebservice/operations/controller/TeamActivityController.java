package de.tum.cit.aet.logos.logoswebservice.operations.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.identity.service.ApiKeyAdminService;
import de.tum.cit.aet.logos.logoswebservice.operations.service.TeamActivityService;

/**
 * One team's live request counts and token spend (issue #776).
 *
 * App administrators wanted what the statistics page gives Logos admins,
 * narrowed to their own teams and cut down to the two questions they actually
 * ask: what is running right now, and what has the team used.
 */
@RestController
public class TeamActivityController {

    private final TeamActivityService teamActivityService;
    private final ApiKeyAdminService apiKeyAdminService;

    public TeamActivityController(TeamActivityService teamActivityService,
                                  ApiKeyAdminService apiKeyAdminService) {
        this.teamActivityService = teamActivityService;
        this.apiKeyAdminService = apiKeyAdminService;
    }

    /**
     * Activity for one team.
     *
     * Team id comes from the path and the check is against that id, so there is
     * no way to widen the scope through the body — the same ownership rule the
     * key admin endpoints apply: a Logos admin sees any team, an app admin only
     * one they own.
     */
    @PostMapping("/logosdb/teams/{teamId}/activity")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> teamActivity(@PathVariable Integer teamId,
                                          @RequestBody(required = false) Map<String, Object> body,
                                          @RequestAttribute("authContext") AuthContext auth) {
        if (teamId == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "team_id is required"));
        }
        if (Role.APP_ADMIN.matches(auth.role())
                && (auth.userId() == null || !apiKeyAdminService.isTeamOwner(teamId, auth.userId()))) {
            return ResponseEntity.status(403).body(Map.of("detail", "Team owner access required"));
        }
        Map<String, Object> payload = body != null ? body : Map.of();
        Integer days = payload.get("days") instanceof Number n ? n.intValue() : null;
        return ResponseEntity.ok(teamActivityService.getTeamActivity(teamId, days));
    }
}
