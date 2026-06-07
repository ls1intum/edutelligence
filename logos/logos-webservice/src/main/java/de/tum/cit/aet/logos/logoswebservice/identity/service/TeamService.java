package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.security.SecureRandom;
import java.util.Base64;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.springframework.jdbc.core.JdbcTemplate;
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

    private static final SecureRandom SECURE_RANDOM = new SecureRandom();

    private final TeamRepository teamRepository;
    private final TeamMemberRepository memberRepository;
    private final UserRepository userRepository;
    private final JdbcTemplate jdbcTemplate;

    public TeamService(TeamRepository teamRepository, TeamMemberRepository memberRepository,
                       UserRepository userRepository, JdbcTemplate jdbcTemplate) {
        this.teamRepository = teamRepository;
        this.memberRepository = memberRepository;
        this.userRepository = userRepository;
        this.jdbcTemplate = jdbcTemplate;
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
            jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM team_model_permissions WHERE team_id = ?",
                Integer.class, t.getId()),
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
            addMember(teamId, new AddTeamMemberRequest(ownerId, true));
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

            Long budgetUsed = jdbcTemplate.queryForObject("""
                SELECT COALESCE(SUM(bu.cost_micro_cents), 0)
                FROM budget_usage bu
                JOIN api_keys ak ON ak.id = bu.api_key_id
                WHERE ak.team_id = ? AND bu.month = DATE_TRUNC('month', CURRENT_DATE)::date
                """, Long.class, teamId);

            Map<String, Object> teamMap = new HashMap<>();
            teamMap.put("id", team.getId());
            teamMap.put("name", team.getName());
            teamMap.put("is_caller_owner", isCallerOwner);
            teamMap.put("budget_used_micro_cents", budgetUsed != null ? budgetUsed : 0L);
            teamMap.put("default_monthly_budget_micro_cents", team.getDefaultMonthlyBudgetMicroCents());
            teamMap.put("team_monthly_budget_micro_cents", team.getTeamMonthlyBudgetMicroCents());
            teamMap.put("default_cloud_rpm_limit", team.getDefaultCloudRpmLimit());
            teamMap.put("default_cloud_tpm_limit", team.getDefaultCloudTpmLimit());
            teamMap.put("default_local_rpm_limit", team.getDefaultLocalRpmLimit());
            teamMap.put("default_local_tpm_limit", team.getDefaultLocalTpmLimit());

            List<Map<String, Object>> members = memberRepository.findById_TeamId(teamId).stream()
                .map(m -> {
                    var user = userRepository.findById(m.getId().getUserId()).orElse(null);
                    Map<String, Object> memberMap = new HashMap<>();
                    memberMap.put("id", m.getId().getUserId());
                    memberMap.put("is_owner", m.getIsOwner());
                    memberMap.put("username", user != null ? user.getUsername() : "");
                    memberMap.put("role", user != null ? user.getRole() : "");
                    memberMap.put("prename", user != null ? user.getPrename() : "");
                    memberMap.put("name", user != null ? user.getName() : "");
                    memberMap.put("email", user != null ? user.getEmail() : "");
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

    public Optional<String> addMember(Integer teamId, AddTeamMemberRequest body) {
        boolean alreadyMember = memberRepository.isMember(teamId, body.user_id());

        TeamMember m = new TeamMember();
        m.setId(new TeamMemberId(body.user_id(), teamId));
        m.setIsOwner(body.is_owner() != null && body.is_owner());
        memberRepository.save(m);

        if (!alreadyMember) {
            var userOpt = userRepository.findById(body.user_id());
            var teamOpt = teamRepository.findById(teamId);
            if (userOpt.isPresent() && teamOpt.isPresent()) {
                var user = userOpt.get();
                var team = teamOpt.get();
                if (!"root".equals(user.getUsername()) && team.getName() != null && !team.getName().isBlank()) {
                    String keyName = user.getUsername() + "-" + team.getName() + "-key";
                    String teamSlug = team.getName().toLowerCase()
                        .replaceAll("[^a-z0-9\\-]", "-")
                        .replaceAll("\\-+", "-")
                        .replaceAll("^\\-|\\-$", "");
                    String userSlug = user.getUsername().toLowerCase()
                        .replaceAll("[^a-z0-9\\-]", "-")
                        .replaceAll("\\-+", "-")
                        .replaceAll("^\\-|\\-$", "");
                    String label = teamSlug + "-" + userSlug;
                    if (label.length() > 35) label = label.substring(0, 35);
                    byte[] bytes = new byte[96];
                    SECURE_RANDOM.nextBytes(bytes);
                    String keyValue = "lg-" + label + "-" + Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
                    jdbcTemplate.update("""
                        INSERT INTO api_keys (key_value, name, key_type, team_id, user_id,
                            environment, log, settings, default_priority, is_active, use_custom_permissions)
                        VALUES (?, ?, CAST('developer' AS api_key_type_enum), ?, ?,
                            '-', CAST('BILLING' AS logging_enum), CAST('{}' AS jsonb), 1, true, false)
                        """,
                        keyValue, keyName, teamId, body.user_id());
                    return Optional.of(keyValue);
                }
            }
        }
        return Optional.empty();
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
