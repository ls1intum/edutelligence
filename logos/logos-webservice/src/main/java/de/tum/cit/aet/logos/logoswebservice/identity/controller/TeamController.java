package de.tum.cit.aet.logos.logoswebservice.identity.controller;

import java.util.List;
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
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateTeamKeycloakGroupRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateTeamMemberRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateTeamPriorityRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateTeamRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.identity.service.KeycloakGroupDirectoryService;
import de.tum.cit.aet.logos.logoswebservice.identity.service.TeamService;

import static de.tum.cit.aet.logos.logoswebservice.identity.controller.UserController.isLogosAdmin;

@RestController
@RequestMapping("/teams")
public class TeamController {

    private final TeamService teamService;
    private final KeycloakGroupDirectoryService groupDirectory;

    public TeamController(TeamService teamService, KeycloakGroupDirectoryService groupDirectory) {
        this.teamService = teamService;
        this.groupDirectory = groupDirectory;
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
        if (body.keycloak_group() != null && !body.keycloak_group().isBlank() && !isLogosAdmin(auth)) {
            return ResponseEntity.status(403).body(Map.of(
                "detail", "Only Logos admins can link a team to a Keycloak group."));
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

    /**
     * Overall queue priority of a team's traffic. The ordering of the team's
     * members (application > app admin > developer) is fixed by the
     * orchestrator; this shifts the whole team within the queue. A platform
     * decision, therefore logos_admin only. Null unsets the priority.
     */
    @PatchMapping("/{teamId}/priority")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> updateTeamPriority(
            @RequestAttribute("authContext") AuthContext auth,
            @PathVariable Integer teamId,
            @RequestBody UpdateTeamPriorityRequestDTO body) {
        Integer priority = body.priority();
        if (priority != null && (priority < 1 || priority > 10)) {
            return ResponseEntity.status(400).body(Map.of(
                "detail", "priority must be between 1 and 10 (or null to unset)"));
        }
        return teamService.updateTeamPriority(teamId, priority)
            .<ResponseEntity<?>>map(ResponseEntity::ok)
            .orElse(ResponseEntity.status(404).body(null));
    }

    /**
     * Links the team to a Keycloak group, so that the group's members join it
     * on their next login and on the nightly directory sync; a null or blank
     * value removes the link. Who belongs to which team is an identity-level
     * decision and a team owner must not be able to pull an arbitrary group
     * into their own team, so this is logos_admin only.
     */
    @PatchMapping("/{teamId}/keycloak-group")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> updateTeamKeycloakGroup(
            @RequestAttribute("authContext") AuthContext auth,
            @PathVariable Integer teamId,
            @RequestBody UpdateTeamKeycloakGroupRequestDTO body) {
        return teamService.updateTeamKeycloakGroup(teamId, body.keycloak_group())
            .<ResponseEntity<?>>map(ResponseEntity::ok)
            .orElse(ResponseEntity.status(404).body(Map.of("detail", "Team not found")));
    }

    /**
     * The groups and realm roles of the configured Keycloak realm, for the
     * group picker. Reports {@code available=false} instead of failing when the
     * deployment has no directory access, so the dialog falls back to free text.
     */
    @GetMapping("/keycloak-groups")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> listKeycloakGroups(@RequestAttribute("authContext") AuthContext auth) {
        return ResponseEntity.ok(groupDirectory.list());
    }

    /** Public stats categories already in use, for the team settings picker. */
    @GetMapping("/public-categories")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<List<String>> listPublicCategories() {
        return ResponseEntity.ok(teamService.publicCategories());
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
