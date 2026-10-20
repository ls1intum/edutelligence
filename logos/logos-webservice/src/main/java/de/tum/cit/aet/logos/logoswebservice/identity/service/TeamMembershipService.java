package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.audit.AuditLogService;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMember;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMemberId;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMemberSource;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;

@Service
public class TeamMembershipService {

    private final TeamMemberRepository memberRepository;
    private final ApiKeyRepository apiKeyRepository;
    private final UserRepository userRepository;
    private final TeamRepository teamRepository;
    private final ApiKeyFactory apiKeyFactory;
    private final AuditLogService auditLog;

    public TeamMembershipService(TeamMemberRepository memberRepository,
                                 ApiKeyRepository apiKeyRepository,
                                 UserRepository userRepository,
                                 TeamRepository teamRepository,
                                 ApiKeyFactory apiKeyFactory,
                                 AuditLogService auditLog) {
        this.memberRepository = memberRepository;
        this.apiKeyRepository = apiKeyRepository;
        this.userRepository = userRepository;
        this.teamRepository = teamRepository;
        this.apiKeyFactory = apiKeyFactory;
        this.auditLog = auditLog;
    }

    @Transactional
    public Optional<String> join(Integer userId, Integer teamId, boolean isOwner, TeamMemberSource source) {
        // Validate invariants before any persistence so that a rejected join
        // doesn't leak a half-baked team_members row.
        var userOpt = userRepository.findById(userId);
        var teamOpt = teamRepository.findById(teamId);
        if (userOpt.isEmpty() || teamOpt.isEmpty()) return Optional.empty();
        var user = userOpt.get();
        var team = teamOpt.get();
        if ("root".equals(user.getUsername()) || team.getName() == null || team.getName().isBlank()) {
            return Optional.empty();
        }

        TeamMemberId memberId = new TeamMemberId(userId, teamId);
        Optional<TeamMember> existingMember = memberRepository.findById(memberId);
        boolean alreadyMember = existingMember.isPresent();

        // Taken before the entity is changed: an existing membership is mutated in
        // place, so a snapshot read afterwards would equal the new state.
        Map<String, Object> before = existingMember.map(TeamMembershipService::snapshot).orElseGet(() -> absent());

        TeamMember member = existingMember.orElseGet(TeamMember::new);
        member.setId(memberId);
        if (!alreadyMember) {
            member.setIsOwner(isOwner);
            member.setSource(source);
        } else if (source == TeamMemberSource.KEYCLOAK) {
            member.setSource(TeamMemberSource.KEYCLOAK);
        }
        memberRepository.save(member);
        auditLog.record("team.member_joined", "team_member", teamId + "/" + userId, teamId,
            before, snapshot(member));

        List<ApiKey> existing = apiKeyRepository.findByUserIdAndTeamIdAndKeyType(userId, teamId, ApiKeyType.developer);
        if (!existing.isEmpty()) {
            ApiKey key = existing.getFirst();
            key.setIsActive(true);
            apiKeyRepository.save(key);
            return Optional.of(key.getKeyValue());
        }

        ApiKey newKey = apiKeyFactory.createDeveloperKey(user, team);
        apiKeyRepository.save(newKey);
        return Optional.of(newKey.getKeyValue());
    }

    /** What the audit trail keeps of a membership. */
    static Map<String, Object> snapshot(TeamMember m) {
        Map<String, Object> s = new LinkedHashMap<>();
        s.put("member", true);
        s.put("is_owner", Boolean.TRUE.equals(m.getIsOwner()));
        s.put("source", m.getSource() == null ? null : m.getSource().name());
        return s;
    }

    static Map<String, Object> absent() {
        Map<String, Object> s = new LinkedHashMap<>();
        s.put("member", false);
        s.put("is_owner", null);
        s.put("source", null);
        return s;
    }

    /** Clears every ownership flag of the user; the memberships themselves stay. */
    @Transactional
    public void revokeOwnerships(Integer userId) {
        for (TeamMember member : memberRepository.findById_UserId(userId)) {
            if (Boolean.TRUE.equals(member.getIsOwner())) {
                Map<String, Object> before = snapshot(member);
                member.setIsOwner(false);
                memberRepository.save(member);
                Integer teamId = member.getId().getTeamId();
                auditLog.record("team.ownership_revoked", "team_member", teamId + "/" + userId, teamId,
                    before, snapshot(member));
            }
        }
    }

    @Transactional
    public void leave(Integer userId, Integer teamId) {
        TeamMemberId memberId = new TeamMemberId(userId, teamId);
        Optional<TeamMember> existing = memberRepository.findById(memberId);
        memberRepository.deleteById(memberId);
        existing.ifPresent(m -> auditLog.record("team.member_removed", "team_member", teamId + "/" + userId, teamId,
            snapshot(m), absent()));

        List<ApiKey> keys = apiKeyRepository.findByUserIdAndTeamIdAndKeyType(userId, teamId, ApiKeyType.developer);
        for (ApiKey key : keys) {
            key.setIsActive(false);
            apiKeyRepository.save(key);
        }
    }
}
