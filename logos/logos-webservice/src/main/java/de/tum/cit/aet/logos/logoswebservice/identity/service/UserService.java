package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import de.tum.cit.aet.logos.logoswebservice.common.ConflictException;
import de.tum.cit.aet.logos.logoswebservice.identity.Csv;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.AddTeamMemberRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.CreateUserRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.ImportUsersRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.TeamResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateUserInfoRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UserResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
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

    @Transactional
    public Optional<UserResponseDTO> updateRole(Integer userId, String role) {
        // Locked read: holds the user row until commit so a concurrent ownership
        // grant (which locks the same row before checking the role) cannot slip
        // in between the ownsAnyTeam check and the demotion.
        return userRepository.findByIdForUpdate(userId).map(user -> {
            requireUnmanaged(user, "given a different role");
            if (Role.APP_DEVELOPER.matches(role) && teamService.ownsAnyTeam(userId)) {
                throw new ConflictException("User '" + user.getUsername()
                    + "' owns a team and team owners need the app_admin or logos_admin role."
                    + " Remove their ownership first.");
            }
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

    /**
     * Parses the uploaded CSV and returns its header row plus the raw data rows
     * so the web application can map columns, let the user pick rows and show a
     * preview before anything is written.
     */
    public Map<String, Object> previewImport(MultipartFile file) throws IOException {
        List<String[]> records = Csv.parse(new String(file.getBytes()));
        List<String> columns = new ArrayList<>();
        List<List<String>> rows = new ArrayList<>();
        for (int i = 0; i < records.size(); i++) {
            if (i == 0) {
                columns = Arrays.asList(records.get(0));
            } else {
                rows.add(Arrays.asList(records.get(i)));
            }
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("columns", columns);
        result.put("rows", rows);
        return result;
    }

    /**
     * Creates the users the web application mapped and selected from the preview.
     * No team is part of the import: users are created as app_developers without
     * one and added to a team's members afterwards.
     */
    public Map<String, Object> importUsers(List<ImportUsersRequestDTO.Row> rowsIn) {
        List<Map<String, Object>> rows = new ArrayList<>();
        int created = 0, existing = 0, failed = 0;
        for (ImportUsersRequestDTO.Row in : rowsIn) {
            String prename = trimToNull(in.prename());
            String name = trimToNull(in.name());
            String email = trimToNull(in.email());
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("email", email);
            row.put("username", null);
            row.put("status", "failed");
            row.put("error", null);
            try {
                if (email != null && userRepository.existsByEmailIgnoreCase(email)) {
                    User existingUser = userRepository.findFirstByEmailIgnoreCase(email).get();
                    row.put("username", existingUser.getUsername());
                    row.put("status", "existing");
                    existing++;
                } else {
                    String username = generateUsername(prename, name);
                    User user = new User();
                    user.setUsername(username);
                    user.setPrename(prename);
                    user.setName(name);
                    user.setEmail(email);
                    user.setRole(Role.APP_DEVELOPER.getValue());
                    user = userRepository.save(user);
                    row.put("username", user.getUsername());
                    row.put("status", "created");
                    created++;
                }
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

    private static String trimToNull(String value) {
        if (value == null) return null;
        String trimmed = value.trim();
        return trimmed.isEmpty() ? null : trimmed;
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
