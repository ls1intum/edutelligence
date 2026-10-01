package de.tum.cit.aet.logos.logoswebservice.identity.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.CreateTeamRepoLinkRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateTeamRepoLinkRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.identity.service.TeamRepoLinkService;

/**
 * Team-scoped GitHub repository links used later for AI-workflow / SLA analysis.
 * Same ownership gate as application keys: logos admins, or an app admin who owns
 * the team.
 */
@RestController
@RequestMapping("/admin")
public class TeamRepoLinkController {

    private final TeamRepoLinkService service;

    public TeamRepoLinkController(TeamRepoLinkService service) {
        this.service = service;
    }

    @GetMapping("/teams/{teamId}/repositories")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> list(
            @PathVariable Integer teamId,
            @RequestAttribute("authContext") AuthContext auth) {
        if (forbiddenForNonOwner(auth, teamId)) {
            return ResponseEntity.status(403).body(Map.of("detail", "Team owner access required"));
        }
        if (!service.teamExists(teamId)) {
            return ResponseEntity.status(404).body(Map.of("detail", "Team not found"));
        }
        return ResponseEntity.ok(service.listForTeam(teamId));
    }

    @PostMapping("/teams/{teamId}/repositories")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> create(
            @PathVariable Integer teamId,
            @RequestBody CreateTeamRepoLinkRequestDTO body,
            @RequestAttribute("authContext") AuthContext auth) {
        if (forbiddenForNonOwner(auth, teamId)) {
            return ResponseEntity.status(403).body(Map.of("detail", "Team owner access required"));
        }
        return ResponseEntity.ok(service.create(teamId, body));
    }

    @PatchMapping("/teams/{teamId}/repositories/{linkId}")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> update(
            @PathVariable Integer teamId,
            @PathVariable Integer linkId,
            @RequestBody UpdateTeamRepoLinkRequestDTO body,
            @RequestAttribute("authContext") AuthContext auth) {
        if (forbiddenForNonOwner(auth, teamId)) {
            return ResponseEntity.status(403).body(Map.of("detail", "Team owner access required"));
        }
        return service.update(teamId, linkId, body)
            .<ResponseEntity<?>>map(ResponseEntity::ok)
            .orElseGet(() -> ResponseEntity.status(404).body(Map.of("detail", "Repository link not found")));
    }

    @DeleteMapping("/teams/{teamId}/repositories/{linkId}")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> delete(
            @PathVariable Integer teamId,
            @PathVariable Integer linkId,
            @RequestAttribute("authContext") AuthContext auth) {
        if (forbiddenForNonOwner(auth, teamId)) {
            return ResponseEntity.status(403).body(Map.of("detail", "Team owner access required"));
        }
        if (!service.delete(teamId, linkId)) {
            return ResponseEntity.status(404).body(Map.of("detail", "Repository link not found"));
        }
        return ResponseEntity.ok(Map.of("message", "Repository link deleted"));
    }

    private boolean forbiddenForNonOwner(AuthContext auth, Integer teamId) {
        return Role.APP_ADMIN.matches(auth.role()) && !service.isTeamOwner(teamId, auth.userId());
    }
}
