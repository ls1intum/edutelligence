package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.util.List;
import java.util.Optional;

import org.springframework.stereotype.Service;

import de.tum.cit.aet.logos.logoswebservice.identity.dto.MeResponse;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.TeamResponse;
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

    public Optional<MeResponse> getMe(Integer userId) {
        return userRepository.findById(userId).map(user -> {
            List<TeamResponse> teams = teamRepository.findTeamsForUser(user.getId()).stream()
                .map(t -> new TeamResponse(t.getId(), t.getName()))
                .toList();
            return new MeResponse(user.getId(), user.getUsername(), user.getEmail(), user.getRole(), teams);
        });
    }
}
