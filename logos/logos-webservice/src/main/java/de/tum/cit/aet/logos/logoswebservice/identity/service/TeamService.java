package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

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

    public TeamService(TeamRepository teamRepository, TeamMemberRepository memberRepository,
                       UserRepository userRepository, TeamBudgetRepository teamBudgetRepository,
                       TeamModelPermissionRepository teamModelPermissionRepository,
                       ApiKeyRepository apiKeyRepository,
                       TeamMembershipService membershipService) {
        this.teamRepository = teamRepository;
        this.memberRepository = memberRepository;
        this.userRepository = userRepository;
        this.teamBudgetRepository = teamBudgetRepository;
        this.teamModelPermissionRepository = teamModelPermissionRepository;
        this.apiKeyRepository = apiKeyRepository;
        this.membershipService = membershipService;
    }

    public List<TeamListResponseDTO> listAllTeams(Integer callerId) {
        return teamRepository.findAll().stream()
            .map(t -> toListDto(t, callerId, true))
            .toList();
    }

    public List<TeamListResponseDTO> listTeamsForUser(Integer userId) {
        return teamRepository.findTeamsForUser(userId).stream()
            .map(t -> toListDto(t, userId, false))
            .toList();
    }

    private TeamListResponseDTO toListDto(Team t, Integer callerId, boolean callerIsLogosAdmin) {
        List<TeamMember> members = memberRepository.findActiveById_TeamId(t.getId());

        List<TeamOwnerResponseDTO> owners = members.stream()
            .filter(m -> Boolean.TRUE.equals(m.getIsOwner()))
            .map(m -> {
                String username = userRepository.findById(m.getId().getUserId())
                    .map(u -> u.getUsername())
                    .orElse("");
                return new TeamOwnerResponseDTO(m.getId().getUserId(), username);
            })
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
            isCallerOwner,
            t.getKeycloakGroup() != null
        );
    }

    public boolean teamNameExists(String name) {
        return teamRepository.findAll().stream().anyMatch(t -> t.getName().equals(name));
    }

    public TeamResponseDTO createTeam(CreateTeamRequestDTO body, Integer callerId) {
        Team team = new Team();
        team.setName(body.name());
        team = teamRepository.save(team);
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

    public boolean deleteTeam(Integer teamId) {
        Optional<Team> teamOpt = teamRepository.findById(teamId);
        if (teamOpt.isEmpty()) return false;
        requireUnmanaged(teamOpt.get(), "deleted");
        teamRepository.deleteById(teamId);
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

    public Optional<TeamResponseDTO> updateTeamLimits(Integer teamId, UpdateTeamRequestDTO body) {
        return teamRepository.findById(teamId).map(team -> {
            if (body.default_cloud_rpm_limit() != null) team.setDefaultCloudRpmLimit(body.default_cloud_rpm_limit());
            if (body.default_cloud_tpm_limit() != null) team.setDefaultCloudTpmLimit(body.default_cloud_tpm_limit());
            if (body.default_local_rpm_limit() != null) team.setDefaultLocalRpmLimit(body.default_local_rpm_limit());
            if (body.default_local_tpm_limit() != null) team.setDefaultLocalTpmLimit(body.default_local_tpm_limit());
            if (body.default_monthly_budget_micro_cents() != null) team.setDefaultMonthlyBudgetMicroCents(body.default_monthly_budget_micro_cents());
            if (body.team_monthly_budget_micro_cents() != null) team.setTeamMonthlyBudgetMicroCents(body.team_monthly_budget_micro_cents());
            teamRepository.save(team);
            return new TeamResponseDTO(team.getId(), team.getName());
        });
    }

    public Optional<TeamResponseDTO> updateTeamName(Integer teamId, String name) {
        return teamRepository.findById(teamId).map(team -> {
            requireUnmanaged(team, "renamed");
            team.setName(name);
            teamRepository.save(team);
            return new TeamResponseDTO(team.getId(), team.getName());
        });
    }

    @Transactional
    public Optional<String> addMember(Integer teamId, AddTeamMemberRequestDTO body) {
        return membershipService.join(body.user_id(), teamId,
            body.is_owner() != null && body.is_owner(), TeamMemberSource.MANUAL);
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

    public boolean updateMember(Integer teamId, Integer userId, UpdateTeamMemberRequestDTO body) {
        TeamMemberId memberId = new TeamMemberId(userId, teamId);
        return memberRepository.findById(memberId).map(m -> {
            if (body.is_owner() != null) m.setIsOwner(body.is_owner());
            memberRepository.save(m);
            return true;
        }).orElse(false);
    }
}
