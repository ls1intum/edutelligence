package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.util.List;
import java.util.Optional;

import org.springframework.stereotype.Service;

import de.tum.cit.aet.logos.logoswebservice.identity.dto.MeResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.TeamResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;

@Service
public class MeService {

    private final UserRepository userRepository;
    private final TeamRepository teamRepository;

    public MeService(UserRepository userRepository, TeamRepository teamRepository) {
        this.userRepository = userRepository;
        this.teamRepository = teamRepository;
    }

    public Optional<MeResponseDTO> getMe(Integer userId) {
        return userRepository.findById(userId).map(user -> {
            List<TeamResponseDTO> teams = teamRepository.findTeamsForUser(user.getId()).stream()
                .map(t -> new TeamResponseDTO(t.getId(), t.getName()))
                .toList();
            return new MeResponseDTO(user.getId(), user.getUsername(), user.getEmail(), user.getRole(), teams);
        });
    }
}
