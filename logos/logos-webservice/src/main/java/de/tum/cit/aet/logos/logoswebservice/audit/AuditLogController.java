package de.tum.cit.aet.logos.logoswebservice.audit;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;

/**
 * Read access to the audit trail. Logos admins read all of it; an app admin
 * reads the trail of a team they own, and only by naming that team.
 */
@RestController
@RequestMapping("/admin")
public class AuditLogController {

    private final AuditLogService service;
    private final TeamMemberRepository memberRepository;

    public AuditLogController(AuditLogService service, TeamMemberRepository memberRepository) {
        this.service = service;
        this.memberRepository = memberRepository;
    }

    @GetMapping("/audit-log")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> list(
            @RequestParam(name = "team_id", required = false) Integer teamId,
            @RequestParam(name = "before_id", required = false) Long beforeId,
            @RequestParam(name = "limit", defaultValue = "50") int limit,
            @RequestAttribute("authContext") AuthContext auth) {
        if (Role.APP_ADMIN.matches(auth.role())
                && (teamId == null || !memberRepository.isOwner(teamId, auth.userId()))) {
            return ResponseEntity.status(403).body(Map.of("detail", "Team owner access required"));
        }
        return ResponseEntity.ok(service.list(teamId, beforeId, limit));
    }
}
