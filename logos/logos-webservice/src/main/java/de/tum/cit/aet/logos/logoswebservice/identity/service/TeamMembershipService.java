package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.util.List;
import java.util.Optional;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

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

    public TeamMembershipService(TeamMemberRepository memberRepository,
                                 ApiKeyRepository apiKeyRepository,
                                 UserRepository userRepository,
                                 TeamRepository teamRepository,
                                 ApiKeyFactory apiKeyFactory) {
        this.memberRepository = memberRepository;
        this.apiKeyRepository = apiKeyRepository;
        this.userRepository = userRepository;
        this.teamRepository = teamRepository;
        this.apiKeyFactory = apiKeyFactory;
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

        TeamMember member = existingMember.orElseGet(TeamMember::new);
        member.setId(memberId);
        if (!alreadyMember) {
            member.setIsOwner(isOwner);
            member.setSource(source);
        } else if (source == TeamMemberSource.KEYCLOAK) {
            member.setSource(TeamMemberSource.KEYCLOAK);
        }
        memberRepository.save(member);

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

    @Transactional
    public void leave(Integer userId, Integer teamId) {
        memberRepository.deleteById(new TeamMemberId(userId, teamId));

        List<ApiKey> keys = apiKeyRepository.findByUserIdAndTeamIdAndKeyType(userId, teamId, ApiKeyType.developer);
        for (ApiKey key : keys) {
            key.setIsActive(false);
            apiKeyRepository.save(key);
        }
    }
}
