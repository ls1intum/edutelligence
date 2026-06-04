package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import de.tum.cit.aet.logos.logoswebservice.identity.dto.CreateUserRequest;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.TeamResponse;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateUserInfoRequest;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UserResponse;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;

@Service
public class UserService {

    private final UserRepository userRepository;
    private final TeamRepository teamRepository;

    public UserService(UserRepository userRepository, TeamRepository teamRepository) {
        this.userRepository = userRepository;
        this.teamRepository = teamRepository;
    }

    public List<UserResponse> listUsers() {
        return userRepository.findAll().stream().map(this::toDto).toList();
    }

    public List<UserResponse> listAdmins() {
        return userRepository.findAdmins().stream().map(this::toDto).toList();
    }

    public UserResponse createUser(CreateUserRequest body) {
        User user = new User();
        user.setUsername(body.username());
        user.setPrename(body.prename());
        user.setName(body.name());
        user.setEmail(body.email());
        user.setRole(body.role());
        return toDto(userRepository.save(user));
    }

    public boolean deleteUser(Integer userId) {
        if (!userRepository.existsById(userId)) return false;
        userRepository.deleteById(userId);
        return true;
    }

    public Optional<UserResponse> updateRole(Integer userId, String role) {
        return userRepository.findById(userId).map(user -> {
            user.setRole(role);
            return toDto(userRepository.save(user));
        });
    }

    public Optional<UserResponse> updateInfo(Integer userId, UpdateUserInfoRequest body) {
        return userRepository.findById(userId).map(user -> {
            if (body.prename() != null) user.setPrename(body.prename());
            if (body.name() != null) user.setName(body.name());
            if (body.email() != null) user.setEmail(body.email());
            return toDto(userRepository.save(user));
        });
    }

    public List<Map<String, Object>> importUsers(MultipartFile file) throws IOException {
        String content = new String(file.getBytes());
        String[] lines = content.split("\n");
        List<Map<String, Object>> results = new ArrayList<>();
        for (int i = 1; i < lines.length; i++) {
            String[] parts = lines[i].trim().split(",");
            if (parts.length < 2) continue;
            try {
                User user = new User();
                user.setUsername(parts[0].trim());
                user.setPrename(parts.length > 1 ? parts[1].trim() : null);
                user.setName(parts.length > 2 ? parts[2].trim() : null);
                user.setEmail(parts.length > 3 ? parts[3].trim() : null);
                user.setRole(parts.length > 4 ? parts[4].trim() : "app_developer");
                userRepository.save(user);
                results.add(Map.of("username", user.getUsername(), "status", "created"));
            } catch (Exception e) {
                results.add(Map.of("username", parts[0].trim(), "status", "failed", "error", e.getMessage()));
            }
        }
        return results;
    }

    public UserResponse toDto(User u) {
        List<TeamResponse> teams = teamRepository.findTeamsForUser(u.getId()).stream()
            .map(t -> new TeamResponse(t.getId(), t.getName()))
            .toList();
        return new UserResponse(u.getId(), u.getUsername(), u.getPrename(), u.getName(), u.getRole(), u.getEmail(), teams);
    }
}
