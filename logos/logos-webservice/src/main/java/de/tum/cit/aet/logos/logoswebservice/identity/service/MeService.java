package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.util.List;
import java.util.Optional;

import org.springframework.stereotype.Service;

import de.tum.cit.aet.logos.logoswebservice.identity.dto.LogosKeyResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.MeResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.TeamResponseDTO;
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
            return new MeResponseDTO(user.getId(), user.getUsername(), user.getEmail(), user.getRole(), teams);
        });
    }

    public Optional<Integer> firstActiveKeyId(Integer userId) {
        if (userId == null) return Optional.empty();
        return apiKeyRepository.findByUserIdAndIsActiveTrue(userId).stream()
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
        return apiKeyRepository.findByUserIdAndIsActiveTrue(userId).stream()
            .map(k -> new LogosKeyResponseDTO(
                k.getId(), k.getName(), k.getKeyValue(), k.getTeamId(),
                k.getTeamId() != null
                    ? teamRepository.findById(k.getTeamId()).map(t -> t.getName()).orElse(null)
                    : null))
            .toList();
    }
}
