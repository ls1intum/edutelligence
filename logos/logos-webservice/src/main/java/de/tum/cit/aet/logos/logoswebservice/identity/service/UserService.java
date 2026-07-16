package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.io.IOException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import de.tum.cit.aet.logos.logoswebservice.common.ConflictException;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.AddTeamMemberRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.CreateUserRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.TeamResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateUserInfoRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UserResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Team;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;

@Service
public class UserService {

    private final UserRepository userRepository;
    private final TeamRepository teamRepository;
    private final TeamService teamService;

    public UserService(UserRepository userRepository, TeamRepository teamRepository, TeamService teamService) {
        this.userRepository = userRepository;
        this.teamRepository = teamRepository;
        this.teamService = teamService;
    }

    public List<UserResponseDTO> listUsers() {
        return userRepository.findByIsActiveTrue().stream().map(this::toDto).toList();
    }

    public List<UserResponseDTO> listAdmins() {
        return userRepository.findAdmins().stream().map(this::toDto).toList();
    }

    public Map<String, Object> createUser(CreateUserRequestDTO body) {
        if (body.email() != null && !body.email().isBlank()
                && userRepository.existsByEmailIgnoreCase(body.email())) {
            throw new DuplicateEmailException();
        }

        String username = generateUsername(body.prename(), body.name());

        User user = new User();
        user.setUsername(username);
        user.setPrename(body.prename());
        user.setName(body.name());
        user.setEmail(body.email());
        user.setRole(body.role());
        User saved = userRepository.save(user);

        List<String> logosKeys = new ArrayList<>();
        if (body.team_ids() != null) {
            for (Integer teamId : body.team_ids()) {
                teamService.addMember(teamId, new AddTeamMemberRequestDTO(saved.getId(), false))
                    .ifPresent(logosKeys::add);
            }
        }

        List<TeamResponseDTO> teams = teamRepository.findTeamsForUser(saved.getId()).stream()
            .map(t -> new TeamResponseDTO(t.getId(), t.getName()))
            .toList();

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("id", saved.getId());
        result.put("username", username);
        result.put("prename", saved.getPrename());
        result.put("name", saved.getName());
        result.put("email", saved.getEmail());
        result.put("role", saved.getRole());
        result.put("teams", teams);
        result.put("managed", saved.getKeycloakId() != null);
        result.put("logos_keys", logosKeys);
        return result;
    }

    public boolean deleteUser(Integer userId) {
        Optional<User> userOpt = userRepository.findById(userId);
        if (userOpt.isEmpty()) return false;
        requireUnmanaged(userOpt.get(), "deleted");
        userRepository.deleteById(userId);
        return true;
    }

    public Optional<UserResponseDTO> updateRole(Integer userId, String role) {
        return userRepository.findById(userId).map(user -> {
            requireUnmanaged(user, "given a different role");
            user.setRole(role);
            return toDto(userRepository.save(user));
        });
    }

    public Optional<String> findRole(Integer userId) {
        return userRepository.findById(userId).map(User::getRole);
    }

    public Optional<UserResponseDTO> updateInfo(Integer userId, UpdateUserInfoRequestDTO body) {
        return userRepository.findById(userId).map(user -> {
            requireUnmanaged(user, "edited");
            if (body.prename() != null) user.setPrename(body.prename());
            if (body.name() != null) user.setName(body.name());
            if (body.email() != null) user.setEmail(body.email());
            return toDto(userRepository.save(user));
        });
    }

    public Map<String, Object> importUsers(MultipartFile file) throws IOException {
        String content = new String(file.getBytes());
        String[] lines = content.split("\n");
        List<Map<String, Object>> rows = new ArrayList<>();
        int created = 0, existing = 0, failed = 0;

        if (lines.length < 2) {
            return Map.of("summary", Map.of("created", 0, "existing", 0, "failed", 0), "rows", rows);
        }

        String[] headers = lines[0].trim().split(",");
        Map<String, Integer> idx = new HashMap<>();
        for (int i = 0; i < headers.length; i++) {
            idx.put(headers[i].trim().toLowerCase(), i);
        }

        for (int i = 1; i < lines.length; i++) {
            String line = lines[i].trim();
            if (line.isEmpty()) continue;
            String[] parts = line.split(",");

            String prename = col(parts, idx, "prename");
            String name = col(parts, idx, "name");
            String email = col(parts, idx, "email");
            String teamName = col(parts, idx, "team");

            Map<String, Object> row = new LinkedHashMap<>();
            row.put("email", email);
            row.put("username", null);
            row.put("apiKey", null);
            row.put("team", teamName);
            row.put("status", "failed");
            row.put("error", null);

            try {
                if (email != null && !email.isBlank() && userRepository.existsByEmailIgnoreCase(email)) {
                    User existingUser = userRepository.findFirstByEmailIgnoreCase(email).get();
                    row.put("username", existingUser.getUsername());

                    if (teamName != null && !teamName.isBlank()) {
                        Team team = teamRepository.findFirstByName(teamName).orElseGet(() -> {
                            Team t = new Team();
                            t.setName(teamName);
                            return teamRepository.save(t);
                        });
                        if (!teamService.isMember(team.getId(), existingUser.getId())) {
                            teamService.addMember(team.getId(), new AddTeamMemberRequestDTO(existingUser.getId(), false))
                                .ifPresent(k -> row.put("apiKey", k));
                        }
                        row.put("team", team.getName());
                    }

                    row.put("status", "existing");
                    existing++;
                    rows.add(row);
                    continue;
                }

                String username = generateUsername(prename, name);
                User user = new User();
                user.setUsername(username);
                user.setPrename(prename);
                user.setName(name);
                user.setEmail(email);
                user.setRole(Role.APP_DEVELOPER.getValue());
                user = userRepository.save(user);
                row.put("username", user.getUsername());

                if (teamName != null && !teamName.isBlank()) {
                    Team team = teamRepository.findByName(teamName).orElseGet(() -> {
                        Team t = new Team();
                        t.setName(teamName);
                        return teamRepository.save(t);
                    });
                    teamService.addMember(team.getId(), new AddTeamMemberRequestDTO(user.getId(), false))
                        .ifPresent(k -> row.put("apiKey", k));
                    row.put("team", team.getName());
                }

                row.put("status", "created");
                created++;
            } catch (Exception e) {
                row.put("error", e.getMessage());
                row.put("status", "failed");
                failed++;
            }
            rows.add(row);
        }

        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("created",  created);
        summary.put("existing", existing);
        summary.put("failed",   failed);
        return Map.of("summary", summary, "rows", rows);
    }

    /**
     * Keycloak owns the identity, role and existence of synced users: every sync
     * overwrites prename/name/email/role and reactivates the account. Editing those
     * locally would just be undone on the next sync, so we reject it outright.
     * Logos-owned data (team limits, key budgets, team ownership) stays editable.
     */
    private void requireUnmanaged(User user, String action) {
        if (user.getKeycloakId() != null) {
            throw new ConflictException("This user is managed by Keycloak and cannot be " + action + " here.");
        }
    }

    private static String col(String[] parts, Map<String, Integer> idx, String header) {
        Integer i = idx.get(header);
        if (i == null || i >= parts.length) return null;
        String val = parts[i].trim();
        return val.isEmpty() ? null : val;
    }

    public UserResponseDTO toDto(User u) {
        List<TeamResponseDTO> teams = teamRepository.findTeamsForUser(u.getId()).stream()
            .map(t -> new TeamResponseDTO(t.getId(), t.getName()))
            .toList();
        return new UserResponseDTO(u.getId(), u.getUsername(), u.getPrename(), u.getName(), u.getRole(), u.getEmail(), teams, u.getKeycloakId() != null);
    }

    private String generateUsername(String prename, String name) {
        String p = prename == null ? "" : prename.strip().toLowerCase().replaceAll("\\s+", "");
        String n = name    == null ? "" : name.strip().toLowerCase().replaceAll("\\s+", "");

        List<String> candidates = new ArrayList<>();
        for (int i = 1; i <= p.length(); i++) {
            candidates.add(p.substring(0, i) + n);
        }
        if (candidates.isEmpty()) candidates.add(n.isBlank() ? "user" : n);

        for (String candidate : candidates) {
            if (!userRepository.existsByUsername(candidate)) return candidate;
        }

        String base = p.isBlank() ? n : (p + n);
        if (base.isBlank()) base = "user";
        for (int i = 2; ; i++) {
            String candidate = base + i;
            if (!userRepository.existsByUsername(candidate)) return candidate;
        }
    }

    public static class DuplicateEmailException extends RuntimeException {
        public DuplicateEmailException() { super("Email already in use"); }
    }
}
