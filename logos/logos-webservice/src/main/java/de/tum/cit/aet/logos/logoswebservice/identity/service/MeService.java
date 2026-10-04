package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;

import org.springframework.stereotype.Service;

import de.tum.cit.aet.logos.logoswebservice.identity.dto.LogosKeyResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.MeResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.TeamResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Team;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;

@Service
public class MeService {

    private final UserRepository userRepository;
    private final TeamRepository teamRepository;
    private final ApiKeyRepository apiKeyRepository;

    public MeService(UserRepository userRepository, TeamRepository teamRepository,
                     ApiKeyRepository apiKeyRepository) {
        this.userRepository = userRepository;
        this.teamRepository = teamRepository;
        this.apiKeyRepository = apiKeyRepository;
    }

    public Optional<MeResponseDTO> getMe(Integer userId) {
        return userRepository.findById(userId).map(user -> {
            List<TeamResponseDTO> teams = teamRepository.findTeamsForUser(user.getId()).stream()
                .map(t -> new TeamResponseDTO(t.getId(), t.getName()))
                .toList();
            return new MeResponseDTO(user.getId(), user.getUsername(), user.getPrename(), user.getName(),
                user.getEmail(), user.getRole(), teams);
        });
    }

    public Optional<Integer> firstActiveKeyId(Integer userId) {
        if (userId == null) return Optional.empty();
        return apiKeyRepository.findByUserIdAndIsActiveTrueOrderByIdAsc(userId).stream()
            .map(de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey::getId)
            .findFirst();
    }

    public boolean userOwnsKey(Integer userId, Integer apiKeyId) {
        if (userId == null || apiKeyId == null) return false;
        return apiKeyRepository.findById(apiKeyId)
            .map(k -> userId.equals(k.getUserId()))
            .orElse(false);
    }

    public List<LogosKeyResponseDTO> getMyKeys(Integer userId) {
        List<ApiKey> keys = apiKeyRepository.findByUserIdAndIsActiveTrue(userId);

        // One batched lookup for all referenced teams instead of a findById per
        // key: a user's key count tracks their team count (one developer key
        // per team), so a per-key query here scales linearly with team count.
        Set<Integer> teamIds = keys.stream()
            .map(ApiKey::getTeamId)
            .filter(id -> id != null)
            .collect(Collectors.toSet());
        Map<Integer, String> teamNamesById = teamRepository.findAllById(teamIds).stream()
            .collect(Collectors.toMap(Team::getId, Team::getName));

        return keys.stream()
            .map(k -> new LogosKeyResponseDTO(
                k.getId(), k.getName(), k.getKeyValue(), k.getTeamId(),
                k.getTeamId() != null ? teamNamesById.get(k.getTeamId()) : null))
            .toList();
    }
}
