package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.audit.AuditLogService;
import de.tum.cit.aet.logos.logoswebservice.common.ConflictException;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.TeamModelPermissionRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.TeamBudgetRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.AddTeamMemberRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.CreateTeamRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.MyTeamDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.MyTeamOwnerDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.TeamListResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.TeamOwnerResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.TeamResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateTeamMemberRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateTeamRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Team;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMember;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMemberId;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMemberSource;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;

@Service
public class TeamService {

    private final TeamRepository teamRepository;
    private final TeamMemberRepository memberRepository;
    private final UserRepository userRepository;
    private final TeamBudgetRepository teamBudgetRepository;
    private final TeamModelPermissionRepository teamModelPermissionRepository;
    private final ApiKeyRepository apiKeyRepository;
    private final TeamMembershipService membershipService;
    private final AuditLogService auditLog;

    public TeamService(TeamRepository teamRepository, TeamMemberRepository memberRepository,
                       UserRepository userRepository, TeamBudgetRepository teamBudgetRepository,
                       TeamModelPermissionRepository teamModelPermissionRepository,
                       ApiKeyRepository apiKeyRepository,
                       TeamMembershipService membershipService,
                       AuditLogService auditLog) {
        this.teamRepository = teamRepository;
        this.memberRepository = memberRepository;
        this.userRepository = userRepository;
        this.teamBudgetRepository = teamBudgetRepository;
        this.teamModelPermissionRepository = teamModelPermissionRepository;
        this.apiKeyRepository = apiKeyRepository;
        this.membershipService = membershipService;
        this.auditLog = auditLog;
    }

    /**
     * Deterministic order for the team listings: without an explicit sort the
     * backing query returns rows in database order, which changes as rows are
     * added and removed, so the table's rows would jump around on every page
     * load. Name (case-insensitive) with the id as a stable tiebreak.
     */
    private static final Comparator<Team> BY_NAME_THEN_ID = Comparator
        .comparing(Team::getName, String.CASE_INSENSITIVE_ORDER)
        .thenComparing(Team::getId);

    public List<TeamListResponseDTO> listAllTeams(Integer callerId) {
        return teamRepository.findAll().stream()
            .sorted(BY_NAME_THEN_ID)
            .map(t -> toListDto(t, callerId, true))
            .toList();
    }

    public List<TeamListResponseDTO> listTeamsForUser(Integer userId) {
        return teamRepository.findTeamsForUser(userId).stream()
            .sorted(BY_NAME_THEN_ID)
            .map(t -> toListDto(t, userId, false))
            .toList();
    }

    private TeamListResponseDTO toListDto(Team t, Integer callerId, boolean callerIsLogosAdmin) {
        List<TeamMember> members = memberRepository.findActiveById_TeamId(t.getId());

        List<TeamOwnerResponseDTO> owners = members.stream()
            .filter(m -> Boolean.TRUE.equals(m.getIsOwner()))
            .map(m -> userRepository.findById(m.getId().getUserId())
                .map(u -> new TeamOwnerResponseDTO(
                    m.getId().getUserId(), u.getUsername(), u.getPrename(), u.getName()))
                .orElse(new TeamOwnerResponseDTO(m.getId().getUserId(), "", "", "")))
            .toList();

        boolean isCallerOwner = callerIsLogosAdmin || members.stream()
            .anyMatch(m -> m.getId().getUserId().equals(callerId) && Boolean.TRUE.equals(m.getIsOwner()));

        return new TeamListResponseDTO(
            t.getId(),
            t.getName(),
            owners,
            members.size(),
            Math.toIntExact(teamModelPermissionRepository.countById_TeamId(t.getId())),
            t.getDefaultCloudRpmLimit(),
            t.getDefaultCloudTpmLimit(),
            t.getDefaultLocalRpmLimit(),
            t.getDefaultLocalTpmLimit(),
            t.getPriority(),
            isCallerOwner,
            t.getKeycloakGroup() != null
        );
    }

    public boolean teamNameExists(String name) {
        return teamRepository.findAll().stream().anyMatch(t -> t.getName().equals(name));
    }

    @Transactional
    public TeamResponseDTO createTeam(CreateTeamRequestDTO body, Integer callerId) {
        Team team = new Team();
        team.setName(body.name());
        team = teamRepository.save(team);
        Map<String, Object> created = new LinkedHashMap<>();
        created.put("exists", true);
        created.put("name", team.getName());
        auditLog.record("team.created", "team", team.getId(), team.getId(),
            Map.of("exists", false), created);
        List<Integer> ownerIds = (body.owner_ids() != null && !body.owner_ids().isEmpty())
            ? body.owner_ids()
            : List.of(callerId);
        final Integer teamId = team.getId();
        for (Integer ownerId : ownerIds) {
            addMember(teamId, new AddTeamMemberRequestDTO(ownerId, true));
        }
        return new TeamResponseDTO(team.getId(), team.getName());
    }

    public boolean isOwner(Integer teamId, Integer userId) {
        return memberRepository.isOwner(teamId, userId);
    }

    public boolean isMember(Integer teamId, Integer userId) {
        return memberRepository.isMember(teamId, userId);
    }

    @Transactional
    public boolean deleteTeam(Integer teamId) {
        Optional<Team> teamOpt = teamRepository.findById(teamId);
        if (teamOpt.isEmpty()) return false;
        requireUnmanaged(teamOpt.get(), "deleted");
        Map<String, Object> gone = new LinkedHashMap<>();
        gone.put("exists", true);
        gone.put("name", teamOpt.get().getName());
        teamRepository.deleteById(teamId);
        auditLog.record("team.deleted", "team", teamId, teamId, gone, Map.of("exists", false));
        return true;
    }

    /**
     * Keycloak owns the name and existence of synced teams (the name is derived from
     * the Keycloak group and membership is reconciled on every login). Renaming or
     * deleting them locally would drift from Keycloak, so we reject it. Logos-owned
     * data (limits, budgets, ownership flags) stays editable for managed teams too.
     */
    private void requireUnmanaged(Team team, String action) {
        if (team.getKeycloakGroup() != null) {
            throw new ConflictException("This team is managed by Keycloak and cannot be " + action + " here.");
        }
    }

    public Optional<Map<String, Object>> getTeamDetail(Integer teamId, Integer callerId, boolean callerIsLogosAdmin) {
        return teamRepository.findById(teamId).map(team -> {
            boolean isCallerOwner = callerIsLogosAdmin || memberRepository.isOwner(teamId, callerId);

            Long budgetUsed = teamBudgetRepository.findBudgetUsedByTeam(teamId).getBudgetUsed();

            Map<String, Object> teamMap = new HashMap<>();
            teamMap.put("id", team.getId());
            teamMap.put("name", team.getName());
            teamMap.put("is_caller_owner", isCallerOwner);
            teamMap.put("managed", team.getKeycloakGroup() != null);
            teamMap.put("budget_used_micro_cents", budgetUsed != null ? budgetUsed : 0L);
            teamMap.put("default_monthly_budget_micro_cents", team.getDefaultMonthlyBudgetMicroCents());
            teamMap.put("team_monthly_budget_micro_cents", team.getTeamMonthlyBudgetMicroCents());
            teamMap.put("default_cloud_rpm_limit", team.getDefaultCloudRpmLimit());
            teamMap.put("default_cloud_tpm_limit", team.getDefaultCloudTpmLimit());
            teamMap.put("default_local_rpm_limit", team.getDefaultLocalRpmLimit());
            teamMap.put("default_local_tpm_limit", team.getDefaultLocalTpmLimit());
            // Same field as the teams list: needed so the application-keys SLO
            // column can show what an unset (inherited) key is actually served as.
            teamMap.put("priority", team.getPriority());
            teamMap.put("show_on_public_stats", team.isShowOnPublicStats());

            List<Map<String, Object>> members = memberRepository.findActiveById_TeamId(teamId).stream()
                .flatMap(m -> userRepository.findById(m.getId().getUserId()).stream().map(user -> {
                    Map<String, Object> memberMap = new HashMap<>();
                    memberMap.put("id", m.getId().getUserId());
                    memberMap.put("is_owner", m.getIsOwner());
                    memberMap.put("managed", m.getSource() == TeamMemberSource.KEYCLOAK);
                    memberMap.put("username", user.getUsername());
                    memberMap.put("role", user.getRole());
                    memberMap.put("prename", user.getPrename());
                    memberMap.put("name", user.getName());
                    memberMap.put("email", user.getEmail());
                    return memberMap;
                }))
                .toList();

            Map<String, Object> result = new HashMap<>();
            result.put("team", teamMap);
            result.put("members", members);
            return result;
        });
    }

    @Transactional
    public Optional<TeamResponseDTO> updateTeamLimits(Integer teamId, UpdateTeamRequestDTO body) {
        return teamRepository.findById(teamId).map(team -> {
            Map<String, Object> before = limitsSnapshot(team);
            if (body.default_cloud_rpm_limit() != null) team.setDefaultCloudRpmLimit(body.default_cloud_rpm_limit());
            if (body.default_cloud_tpm_limit() != null) team.setDefaultCloudTpmLimit(body.default_cloud_tpm_limit());
            if (body.default_local_rpm_limit() != null) team.setDefaultLocalRpmLimit(body.default_local_rpm_limit());
            if (body.default_local_tpm_limit() != null) team.setDefaultLocalTpmLimit(body.default_local_tpm_limit());
            if (body.default_monthly_budget_micro_cents() != null) team.setDefaultMonthlyBudgetMicroCents(body.default_monthly_budget_micro_cents());
            if (body.team_monthly_budget_micro_cents() != null) team.setTeamMonthlyBudgetMicroCents(body.team_monthly_budget_micro_cents());
            if (body.show_on_public_stats() != null) team.setShowOnPublicStats(body.show_on_public_stats());
            teamRepository.save(team);
            auditLog.record("team.limits_updated", "team", team.getId(), team.getId(), before, limitsSnapshot(team));
            return new TeamResponseDTO(team.getId(), team.getName());
        });
    }

    private static Map<String, Object> limitsSnapshot(Team team) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("default_cloud_rpm_limit", team.getDefaultCloudRpmLimit());
        m.put("default_cloud_tpm_limit", team.getDefaultCloudTpmLimit());
        m.put("default_local_rpm_limit", team.getDefaultLocalRpmLimit());
        m.put("default_local_tpm_limit", team.getDefaultLocalTpmLimit());
        m.put("default_monthly_budget_micro_cents", team.getDefaultMonthlyBudgetMicroCents());
        m.put("team_monthly_budget_micro_cents", team.getTeamMonthlyBudgetMicroCents());
        m.put("show_on_public_stats", team.isShowOnPublicStats());
        return m;
    }

    public Optional<TeamResponseDTO> updateTeamName(Integer teamId, String name) {
        return teamRepository.findById(teamId).map(team -> {
            requireUnmanaged(team, "renamed");
            team.setName(name);
            teamRepository.save(team);
            return new TeamResponseDTO(team.getId(), team.getName());
        });
    }

    /**
     * Sets (or, with null, unsets) the queue priority of a team's traffic.
     * The priority is a platform-level decision, so the endpoint is gated to
     * logos_admin only. Null restores the policy-level priority behaviour.
     */
    public Optional<TeamResponseDTO> updateTeamPriority(Integer teamId, Integer priority) {
        return teamRepository.findById(teamId).map(team -> {
            team.setPriority(priority);
            teamRepository.save(team);
            return new TeamResponseDTO(team.getId(), team.getName());
        });
    }

    @Transactional
    public Optional<String> addMember(Integer teamId, AddTeamMemberRequestDTO body) {
        boolean isOwner = body.is_owner() != null && body.is_owner();
        if (isOwner) requireOwnerCapableRole(body.user_id());
        return membershipService.join(body.user_id(), teamId, isOwner, TeamMemberSource.MANUAL);
    }

    public boolean ownsAnyTeam(Integer userId) {
        return memberRepository.existsById_UserIdAndIsOwnerTrue(userId);
    }

    /**
     * Team management (endpoints and UI) is gated on the app_admin/logos_admin
     * role, so an app_developer owner could never manage the team they own.
     * Reject every attempt to grant ownership to a user without such a role.
     *
     * The locked read keeps the user row until the surrounding transaction
     * commits, so a concurrent role demotion (which takes the same lock before
     * checking ownership) cannot interleave with the grant. Callers must run
     * inside a transaction.
     */
    private void requireOwnerCapableRole(Integer userId) {
        userRepository.findByIdForUpdate(userId).ifPresent(user -> {
            if (!Role.APP_ADMIN.matches(user.getRole()) && !Role.LOGOS_ADMIN.matches(user.getRole())) {
                throw new ConflictException("User '" + user.getUsername()
                    + "' cannot own a team: owners need the app_admin or logos_admin role.");
            }
        });
    }

    public List<MyTeamDTO> listMyTeams(Integer userId) {
        return memberRepository.findById_UserId(userId).stream()
            .map(membership -> {
                Integer teamId = membership.getId().getTeamId();
                Team team = teamRepository.findById(teamId).orElseThrow();
                List<TeamMember> activeMembers = memberRepository.findActiveById_TeamId(teamId);
                Long budgetUsed = teamBudgetRepository.findBudgetUsedByTeam(teamId).getBudgetUsed();

                List<MyTeamOwnerDTO> owners = activeMembers.stream()
                    .filter(m -> Boolean.TRUE.equals(m.getIsOwner()))
                    .map(m -> {
                        var u = userRepository.findById(m.getId().getUserId()).orElse(null);
                        return new MyTeamOwnerDTO(
                            m.getId().getUserId(),
                            u != null && u.getPrename() != null ? u.getPrename() : "",
                            u != null && u.getName() != null ? u.getName() : ""
                        );
                    })
                    .toList();

                return new MyTeamDTO(
                    team.getId(),
                    team.getName(),
                    membership.getIsOwner(),
                    team.getTeamMonthlyBudgetMicroCents(),
                    budgetUsed != null ? budgetUsed : 0L,
                    activeMembers.size(),
                    owners
                );
            })
            .toList();
    }

    public void removeMember(Integer teamId, Integer userId) {
        memberRepository.findById(new TeamMemberId(userId, teamId)).ifPresent(m -> {
            if (m.getSource() == TeamMemberSource.KEYCLOAK) {
                throw new ConflictException(
                    "This membership is managed by Keycloak and cannot be removed here.");
            }
        });
        membershipService.leave(userId, teamId);
    }

    @Transactional
    public boolean updateMember(Integer teamId, Integer userId, UpdateTeamMemberRequestDTO body) {
        TeamMemberId memberId = new TeamMemberId(userId, teamId);
        return memberRepository.findById(memberId).map(m -> {
            if (Boolean.TRUE.equals(body.is_owner())) requireOwnerCapableRole(userId);
            Map<String, Object> before = TeamMembershipService.snapshot(m);
            if (body.is_owner() != null) m.setIsOwner(body.is_owner());
            memberRepository.save(m);
            auditLog.record("team.member_updated", "team_member", teamId + "/" + userId, teamId,
                before, TeamMembershipService.snapshot(m));
            return true;
        }).orElse(false);
    }
}
