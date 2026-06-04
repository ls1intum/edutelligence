package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.springframework.stereotype.Service;

import de.tum.cit.aet.logos.logoswebservice.identity.dto.AddTeamMemberRequest;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.CreateTeamRequest;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.TeamListResponse;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.TeamOwnerResponse;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.TeamResponse;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateTeamMemberRequest;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateTeamRequest;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Team;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMember;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMemberId;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;

@Service
public class TeamService {

    private final TeamRepository teamRepository;
    private final TeamMemberRepository memberRepository;
    private final UserRepository userRepository;

    public TeamService(TeamRepository teamRepository, TeamMemberRepository memberRepository,
                       UserRepository userRepository) {
        this.teamRepository = teamRepository;
        this.memberRepository = memberRepository;
        this.userRepository = userRepository;
    }

    public List<TeamListResponse> listAllTeams(Integer callerId) {
        return teamRepository.findAll().stream()
            .map(t -> toListDto(t, callerId, true))
            .toList();
    }

    public List<TeamListResponse> listTeamsForUser(Integer userId) {
        return teamRepository.findTeamsForUser(userId).stream()
            .map(t -> toListDto(t, userId, false))
            .toList();
    }

    private TeamListResponse toListDto(Team t, Integer callerId, boolean callerIsLogosAdmin) {
        List<TeamMember> members = memberRepository.findById_TeamId(t.getId());

        List<TeamOwnerResponse> owners = members.stream()
            .filter(m -> Boolean.TRUE.equals(m.getIsOwner()))
            .map(m -> {
                String username = userRepository.findById(m.getId().getUserId())
                    .map(u -> u.getUsername())
                    .orElse("");
                return new TeamOwnerResponse(m.getId().getUserId(), username);
            })
            .toList();

        boolean isCallerOwner = callerIsLogosAdmin || members.stream()
            .anyMatch(m -> m.getId().getUserId().equals(callerId) && Boolean.TRUE.equals(m.getIsOwner()));

        return new TeamListResponse(
            t.getId(),
            t.getName(),
            owners,
            members.size(),
            0, // model_count: not yet implemented in Spring Boot
            t.getDefaultCloudRpmLimit(),
            t.getDefaultCloudTpmLimit(),
            t.getDefaultLocalRpmLimit(),
            t.getDefaultLocalTpmLimit(),
            isCallerOwner
        );
    }

    public boolean teamNameExists(String name) {
        return teamRepository.findAll().stream().anyMatch(t -> t.getName().equals(name));
    }

    public TeamResponse createTeam(CreateTeamRequest body, Integer callerId) {
        Team team = new Team();
        team.setName(body.name());
        team = teamRepository.save(team);
        List<Integer> ownerIds = (body.owner_ids() != null && !body.owner_ids().isEmpty())
            ? body.owner_ids()
            : List.of(callerId);
        final Integer teamId = team.getId();
        for (Integer ownerId : ownerIds) {
            TeamMember m = new TeamMember();
            m.setId(new TeamMemberId(ownerId, teamId));
            m.setIsOwner(true);
            memberRepository.save(m);
        }
        return new TeamResponse(team.getId(), team.getName());
    }

    public boolean isOwner(Integer teamId, Integer userId) {
        return memberRepository.isOwner(teamId, userId);
    }

    public boolean isMember(Integer teamId, Integer userId) {
        return memberRepository.isMember(teamId, userId);
    }

    public boolean deleteTeam(Integer teamId) {
        if (!teamRepository.existsById(teamId)) return false;
        teamRepository.deleteById(teamId);
        return true;
    }

    public Optional<Map<String, Object>> getTeamDetail(Integer teamId, Integer callerId, boolean callerIsLogosAdmin) {
        return teamRepository.findById(teamId).map(team -> {
            boolean isCallerOwner = callerIsLogosAdmin || memberRepository.isOwner(teamId, callerId);

            Map<String, Object> teamMap = new HashMap<>();
            teamMap.put("id", team.getId());
            teamMap.put("name", team.getName());
            teamMap.put("is_caller_owner", isCallerOwner);
            teamMap.put("budget_used_micro_cents", 0L);

            List<Map<String, Object>> members = memberRepository.findById_TeamId(teamId).stream()
                .map(m -> {
                    var user = userRepository.findById(m.getId().getUserId()).orElse(null);
                    Map<String, Object> memberMap = new HashMap<>();
                    memberMap.put("user_id", m.getId().getUserId());
                    memberMap.put("is_owner", m.getIsOwner());
                    memberMap.put("username", user != null ? user.getUsername() : "");
                    memberMap.put("role", user != null ? user.getRole() : "");
                    return memberMap;
                })
                .toList();

            Map<String, Object> result = new HashMap<>();
            result.put("team", teamMap);
            result.put("members", members);
            return result;
        });
    }

    public Optional<TeamResponse> updateTeamLimits(Integer teamId, UpdateTeamRequest body) {
        return teamRepository.findById(teamId).map(team -> {
            if (body.default_cloud_rpm_limit() != null) team.setDefaultCloudRpmLimit(body.default_cloud_rpm_limit());
            if (body.default_cloud_tpm_limit() != null) team.setDefaultCloudTpmLimit(body.default_cloud_tpm_limit());
            if (body.default_local_rpm_limit() != null) team.setDefaultLocalRpmLimit(body.default_local_rpm_limit());
            if (body.default_local_tpm_limit() != null) team.setDefaultLocalTpmLimit(body.default_local_tpm_limit());
            if (body.default_monthly_budget_micro_cents() != null) team.setDefaultMonthlyBudgetMicroCents(body.default_monthly_budget_micro_cents());
            if (body.team_monthly_budget_micro_cents() != null) team.setTeamMonthlyBudgetMicroCents(body.team_monthly_budget_micro_cents());
            teamRepository.save(team);
            return new TeamResponse(team.getId(), team.getName());
        });
    }

    public Optional<TeamResponse> updateTeamName(Integer teamId, String name) {
        return teamRepository.findById(teamId).map(team -> {
            team.setName(name);
            teamRepository.save(team);
            return new TeamResponse(team.getId(), team.getName());
        });
    }

    public void addMember(Integer teamId, AddTeamMemberRequest body) {
        TeamMember m = new TeamMember();
        m.setId(new TeamMemberId(body.user_id(), teamId));
        m.setIsOwner(body.is_owner() != null && body.is_owner());
        memberRepository.save(m);
    }

    public void removeMember(Integer teamId, Integer userId) {
        memberRepository.deleteById(new TeamMemberId(userId, teamId));
    }

    public boolean updateMember(Integer teamId, Integer userId, UpdateTeamMemberRequest body) {
        TeamMemberId memberId = new TeamMemberId(userId, teamId);
        return memberRepository.findById(memberId).map(m -> {
            if (body.is_owner() != null) m.setIsOwner(body.is_owner());
            memberRepository.save(m);
            return true;
        }).orElse(false);
    }
}
