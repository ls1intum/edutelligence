package de.tum.cit.aet.logos.logoswebservice.identity.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.ReviewRecommendationRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.StoreDeployKeyRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.identity.service.AiWorkflowAnalysisService;

/**
 * AI workflow analysis and SLA recommendation review for linked repositories.
 * Same ownership gate as {@link TeamRepoLinkController}: logos admins, or an
 * app admin who owns the team.
 */
@RestController
@RequestMapping("/admin")
public class AiWorkflowController {

    private final AiWorkflowAnalysisService service;

    public AiWorkflowController(AiWorkflowAnalysisService service) {
        this.service = service;
    }

    @GetMapping("/teams/{teamId}/workflows")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> listWorkflows(
            @PathVariable Integer teamId,
            @RequestAttribute("authContext") AuthContext auth) {
        if (forbiddenForNonOwner(auth, teamId)) {
            return ResponseEntity.status(403).body(Map.of("detail", "Team owner access required"));
        }
        if (!service.teamExists(teamId)) {
            return ResponseEntity.status(404).body(Map.of("detail", "Team not found"));
        }
        return ResponseEntity.ok(service.listTeamWorkflows(teamId));
    }

    @PostMapping("/teams/{teamId}/repositories/{linkId}/analyze/agent")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> analyzeAgent(
            @PathVariable Integer teamId,
            @PathVariable Integer linkId,
            @RequestAttribute("authContext") AuthContext auth) {
        if (forbiddenForNonOwner(auth, teamId)) {
            return ResponseEntity.status(403).body(Map.of("detail", "Team owner access required"));
        }
        return ResponseEntity.ok(service.queueAgentAnalysis(teamId, linkId));
    }

    @PostMapping("/teams/{teamId}/recommendations/{recId}/review")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> reviewRecommendation(
            @PathVariable Integer teamId,
            @PathVariable Integer recId,
            @RequestBody ReviewRecommendationRequestDTO body,
            @RequestAttribute("authContext") AuthContext auth) {
        if (forbiddenForNonOwner(auth, teamId)) {
            return ResponseEntity.status(403).body(Map.of("detail", "Team owner access required"));
        }
        return ResponseEntity.ok(service.reviewRecommendation(teamId, recId, body, auth.userId()));
    }

    @PutMapping("/teams/{teamId}/repositories/{linkId}/credentials")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> storeCredentials(
            @PathVariable Integer teamId,
            @PathVariable Integer linkId,
            @RequestBody StoreDeployKeyRequestDTO body,
            @RequestAttribute("authContext") AuthContext auth) {
        if (forbiddenForNonOwner(auth, teamId)) {
            return ResponseEntity.status(403).body(Map.of("detail", "Team owner access required"));
        }
        return ResponseEntity.ok(service.storeDeployKey(teamId, linkId, body));
    }

    @DeleteMapping("/teams/{teamId}/repositories/{linkId}/credentials")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> revokeCredentials(
            @PathVariable Integer teamId,
            @PathVariable Integer linkId,
            @RequestAttribute("authContext") AuthContext auth) {
        if (forbiddenForNonOwner(auth, teamId)) {
            return ResponseEntity.status(403).body(Map.of("detail", "Team owner access required"));
        }
        if (!service.revokeCredentials(teamId, linkId)) {
            return ResponseEntity.status(404).body(Map.of("detail", "Credentials not found"));
        }
        return ResponseEntity.ok(Map.of("message", "Credentials revoked"));
    }

    private boolean forbiddenForNonOwner(AuthContext auth, Integer teamId) {
        return Role.APP_ADMIN.matches(auth.role()) && !service.isTeamOwner(teamId, auth.userId());
    }
}
