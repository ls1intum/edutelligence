package de.tum.cit.aet.logos.logoswebservice.identity.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpsertTeamProviderBudgetRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.identity.service.TeamProviderBudgetService;

/**
 * Per-provider monthly budgets for a team (sponsored / dedicated caps).
 * Same ownership gate as team settings: logos admins, or an app admin who owns
 * the team.
 */
@RestController
@RequestMapping("/admin")
public class TeamProviderBudgetController {

    private final TeamProviderBudgetService service;

    public TeamProviderBudgetController(TeamProviderBudgetService service) {
        this.service = service;
    }

    @GetMapping("/teams/{teamId}/provider-budgets")
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

    @PutMapping("/teams/{teamId}/provider-budgets/{providerId}")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> upsert(
            @PathVariable Integer teamId,
            @PathVariable Integer providerId,
            @RequestBody UpsertTeamProviderBudgetRequestDTO body,
            @RequestAttribute("authContext") AuthContext auth) {
        if (forbiddenForNonOwner(auth, teamId)) {
            return ResponseEntity.status(403).body(Map.of("detail", "Team owner access required"));
        }
        UpsertTeamProviderBudgetRequestDTO request = body == null
            ? new UpsertTeamProviderBudgetRequestDTO(providerId, null)
            : new UpsertTeamProviderBudgetRequestDTO(providerId, body.monthly_budget_micro_cents());
        return ResponseEntity.ok(service.upsert(teamId, request));
    }

    @DeleteMapping("/teams/{teamId}/provider-budgets/{providerId}")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> delete(
            @PathVariable Integer teamId,
            @PathVariable Integer providerId,
            @RequestAttribute("authContext") AuthContext auth) {
        if (forbiddenForNonOwner(auth, teamId)) {
            return ResponseEntity.status(403).body(Map.of("detail", "Team owner access required"));
        }
        if (!service.delete(teamId, providerId)) {
            return ResponseEntity.status(404).body(Map.of("detail", "Provider budget not found"));
        }
        return ResponseEntity.ok(Map.of("message", "Provider budget removed"));
    }

    private boolean forbiddenForNonOwner(AuthContext auth, Integer teamId) {
        return Role.APP_ADMIN.matches(auth.role()) && !service.isTeamOwner(teamId, auth.userId());
    }
}
