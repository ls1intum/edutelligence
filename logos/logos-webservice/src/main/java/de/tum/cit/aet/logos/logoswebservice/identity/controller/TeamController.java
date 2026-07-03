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
import de.tum.cit.aet.logos.logoswebservice.identity.dto.AddTeamMemberRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.CreateTeamRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateTeamMemberRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateTeamRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.identity.service.TeamService;

import static de.tum.cit.aet.logos.logoswebservice.identity.controller.UserController.isLogosAdmin;

@RestController
@RequestMapping("/teams")
public class TeamController {

    private final TeamService teamService;

    public TeamController(TeamService teamService) {
        this.teamService = teamService;
    }

    @GetMapping
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> listTeams(@RequestAttribute("authContext") AuthContext auth) {
        return ResponseEntity.ok(isLogosAdmin(auth)
            ? teamService.listAllTeams(auth.userId())
            : teamService.listTeamsForUser(auth.userId()));
    }

    @GetMapping("/mine")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "', '" + Role.Names.APP_DEVELOPER + "')")
    public ResponseEntity<?> listMyTeams(@RequestAttribute("authContext") AuthContext auth) {
        return ResponseEntity.ok(teamService.listMyTeams(auth.userId()));
    }

    @PostMapping
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> createTeam(
            @RequestAttribute("authContext") AuthContext auth,
            @RequestBody CreateTeamRequestDTO body) {
        if (teamService.teamNameExists(body.name())) {
            return ResponseEntity.status(409).body(Map.of("detail", "A team with this name already exists."));
        }
        return ResponseEntity.ok(teamService.createTeam(body, auth.userId()));
    }

    @DeleteMapping("/{teamId}")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> deleteTeam(
            @RequestAttribute("authContext") AuthContext auth,
            @PathVariable Integer teamId) {
        if (Role.APP_ADMIN.matches(auth.role()) && !teamService.isOwner(teamId, auth.userId())) {
            return ResponseEntity.status(403).body(Map.of("detail", "You do not own this team"));
        }
        if (!teamService.deleteTeam(teamId)) {
            return ResponseEntity.status(404).body(Map.of("detail", "Team not found"));
        }
        return ResponseEntity.ok(Map.of("message", "Team deleted"));
    }

    @GetMapping("/{teamId}/members")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> getTeamDetail(
            @RequestAttribute("authContext") AuthContext auth,
            @PathVariable Integer teamId) {
        if (Role.APP_ADMIN.matches(auth.role()) && !teamService.isMember(teamId, auth.userId())) {
            return ResponseEntity.status(403).body(Map.of("detail", "You are not a member of this team"));
        }
        return teamService.getTeamDetail(teamId, auth.userId(), isLogosAdmin(auth))
            .<ResponseEntity<?>>map(ResponseEntity::ok)
            .orElse(ResponseEntity.status(404).body(Map.of("detail", "Team not found")));
    }

    @PatchMapping("/{teamId}")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> updateTeamLimits(
            @RequestAttribute("authContext") AuthContext auth,
            @PathVariable Integer teamId,
            @RequestBody UpdateTeamRequestDTO body) {
        if (Role.APP_ADMIN.matches(auth.role()) && !teamService.isOwner(teamId, auth.userId())) {
            return ResponseEntity.status(403).body(Map.of("detail", "Insufficient permissions"));
        }
        return teamService.updateTeamLimits(teamId, body)
            .<ResponseEntity<?>>map(ResponseEntity::ok)
            .orElse(ResponseEntity.status(404).body(null));
    }

    @PatchMapping("/{teamId}/name")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> updateTeamName(
            @RequestAttribute("authContext") AuthContext auth,
            @PathVariable Integer teamId,
            @RequestBody Map<String, String> body) {
        if (Role.APP_ADMIN.matches(auth.role()) && !teamService.isOwner(teamId, auth.userId())) {
            return ResponseEntity.status(403).body(Map.of("detail", "Insufficient permissions"));
        }
        return teamService.updateTeamName(teamId, body.get("name"))
            .<ResponseEntity<?>>map(ResponseEntity::ok)
            .orElse(ResponseEntity.status(404).body(null));
    }

    @PostMapping("/{teamId}/members")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> addMember(
            @RequestAttribute("authContext") AuthContext auth,
            @PathVariable Integer teamId,
            @RequestBody AddTeamMemberRequestDTO body) {
        if (Role.APP_ADMIN.matches(auth.role()) && !teamService.isOwner(teamId, auth.userId())) {
            return ResponseEntity.status(403).body(Map.of("detail", "You do not own this team"));
        }
        teamService.addMember(teamId, body);
        return ResponseEntity.ok(Map.of("message", "Member added"));
    }

    @DeleteMapping("/{teamId}/members/{userId}")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> removeMember(
            @RequestAttribute("authContext") AuthContext auth,
            @PathVariable Integer teamId,
            @PathVariable Integer userId) {
        if (Role.APP_ADMIN.matches(auth.role())) {
            if (!teamService.isOwner(teamId, auth.userId())) {
                return ResponseEntity.status(403).body(Map.of("detail", "You do not own this team"));
            }
            if (auth.userId().equals(userId)) {
                return ResponseEntity.status(403).body(Map.of("detail", "You cannot remove yourself from a team"));
            }
        }
        teamService.removeMember(teamId, userId);
        return ResponseEntity.ok(Map.of("message", "Member removed"));
    }

    @PatchMapping("/{teamId}/members/{userId}")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> updateMember(
            @RequestAttribute("authContext") AuthContext auth,
            @PathVariable Integer teamId,
            @PathVariable Integer userId,
            @RequestBody UpdateTeamMemberRequestDTO body) {
        if (!teamService.updateMember(teamId, userId, body)) {
            return ResponseEntity.status(404).body(null);
        }
        return ResponseEntity.ok(Map.of("message", "Member updated"));
    }
}
