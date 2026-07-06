package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.time.Duration;
import java.time.Instant;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.common.ConflictException;
import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakClaims;
import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakProperties;
import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakRoleMapper;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Team;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMember;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMemberSource;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;

@Service
public class KeycloakUserSyncService {

    private final UserRepository userRepository;
    private final TeamRepository teamRepository;
    private final TeamMemberRepository memberRepository;
    private final ApiKeyRepository apiKeyRepository;
    private final TeamMembershipService membershipService;
    private final KeycloakRoleMapper roleMapper;
    private final KeycloakProperties props;
    private final KeycloakTeamAutoProvisioner teamAutoProvisioner;

    public KeycloakUserSyncService(UserRepository userRepository, TeamRepository teamRepository,
                                   TeamMemberRepository memberRepository, ApiKeyRepository apiKeyRepository,
                                   TeamMembershipService membershipService,
                                   KeycloakRoleMapper roleMapper, KeycloakProperties props,
                                   KeycloakTeamAutoProvisioner teamAutoProvisioner) {
        this.userRepository = userRepository;
        this.teamRepository = teamRepository;
        this.memberRepository = memberRepository;
        this.apiKeyRepository = apiKeyRepository;
        this.membershipService = membershipService;
        this.roleMapper = roleMapper;
        this.props = props;
        this.teamAutoProvisioner = teamAutoProvisioner;
    }

    @Transactional(readOnly = true)
    public Optional<User> findIfFresh(KeycloakClaims claims) {
        Instant cutoff = Instant.now().minus(Duration.ofMinutes(props.syncDebounceMinutes()));
        return userRepository.findByKeycloakId(UUID.fromString(claims.keycloakId()))
            .filter(user -> {
                if (user.getLastSyncedAt() == null || !user.getLastSyncedAt().isAfter(cutoff)) {
                    return false;
                }
                if (!user.isActive()) {
                    return claims.issuedAt() != null && claims.issuedAt().isBefore(user.getLastSyncedAt());
                }
                return true;
            });
    }

    @Transactional
    public User syncIfStale(KeycloakClaims claims) {
        return findIfFresh(claims).orElseGet(() -> syncFromClaims(claims));
    }

    @Transactional
    public User syncFromClaims(KeycloakClaims claims) {
        UUID keycloakId = UUID.fromString(claims.keycloakId());
        User user = findOrCreate(keycloakId, claims);

        boolean isNew = user.getId() == null;
        boolean wasInactive = !isNew && !user.isActive();

        user.setKeycloakId(keycloakId);
        if (isNew) {
            String prename = claims.prename() != null ? claims.prename() : "";
            String name = claims.name() != null ? claims.name() : "";
            String supplied = claims.username();
            if (supplied != null && !supplied.isBlank()
                && !userRepository.existsByUsername(supplied)) {
                user.setUsername(supplied);
            } else {
                user.setUsername(generateUniqueUsername(prename, name));
            }
        }
        user.setPrename(claims.prename() != null ? claims.prename() : "");
        user.setName(claims.name() != null ? claims.name() : "");
        if (claims.email() != null) user.setEmail(claims.email());
        user.setRole(roleMapper.mapRole(claims.roleNames()));
        user.setActive(true);
        user.setLastSyncedAt(Instant.now());
        user = userRepository.save(user);

        if (wasInactive) reactivateUserKeys(user);
        deactivatePersonalKeys(user);
        syncTeamMemberships(user, claims.roleNames());
        return user;
    }

    @Transactional
    public void deactivateUser(User user) {
        user.setActive(false);
        user.setLastSyncedAt(Instant.now());
        userRepository.save(user);
        apiKeyRepository.findByUserId(user.getId()).forEach(k -> {
            k.setIsActive(false);
            apiKeyRepository.save(k);
        });
    }

    private User findOrCreate(UUID keycloakId, KeycloakClaims claims) {
        Optional<User> byId = userRepository.findByKeycloakId(keycloakId);
        if (byId.isPresent()) return byId.get();

        if (claims.email() != null) {
            Optional<User> byEmail = userRepository.findByEmailIgnoreCase(claims.email());
            if (byEmail.isPresent()) {
                User existing = byEmail.get();
                // Adopt an as-yet-unlinked row (seed/admin-created user signing in for the first time).
                if (existing.getKeycloakId() == null) return existing;
                // The email belongs to a *different* Keycloak subject (we already established no row
                // matches the current sub). We deliberately do not relink — letting a new subject
                // absorb an existing account is an account-takeover vector. Falling through would
                // attempt an insert that dies with an opaque idx_users_email violation, so surface a
                // clear, actionable 409 instead. Happens when an account is recreated or migrated.
                throw new ConflictException(
                    "Email " + claims.email() + " is already linked to Keycloak subject "
                    + existing.getKeycloakId() + ", but this login presented subject " + keycloakId
                    + ". The user's keycloak_id must be reconciled before they can sign in.");
            }
        }

        String prename = claims.prename() != null ? claims.prename() : "";
        String name = claims.name() != null ? claims.name() : "";
        if (!prename.isBlank() && !name.isBlank()) {
            List<User> byName = userRepository
                .findByPrenameIgnoreCaseAndNameIgnoreCaseAndKeycloakIdIsNull(prename, name);
            if (byName.size() == 1) return byName.get(0);
        }

        return new User();
    }

    private String generateUniqueUsername(String prename, String name) {
        String p = prename.toLowerCase().replaceAll("[^a-z]", "");
        String n = name.toLowerCase().replaceAll("[^a-z]", "");
        if (p.isEmpty() && n.isEmpty()) p = "user";

        for (int i = 1; i <= p.length(); i++) {
            String candidate = p.substring(0, i) + n;
            if (!userRepository.existsByUsername(candidate)) return candidate;
        }
        if (p.isEmpty() && !userRepository.existsByUsername(n)) return n;

        String base = p.isEmpty() ? n : p.substring(0, 1) + n;
        for (int i = 1; i <= 999; i++) {
            String candidate = base + i;
            if (!userRepository.existsByUsername(candidate)) return candidate;
        }
        return base + UUID.randomUUID().toString().replace("-", "").substring(0, 6);
    }

    private void reactivateUserKeys(User user) {
        apiKeyRepository.findByUserId(user.getId()).forEach(k -> {
            k.setIsActive(true);
            apiKeyRepository.save(k);
        });
    }

    /**
     * Deactivate any team-less ("personal") developer keys.
     *
     * <p>logos_admins used to receive an auto-provisioned team-less key that the
     * orchestrator treated as a master key (unlimited model/provider access, no
     * rate limit or budget). Admins now obtain keys through team membership like
     * every other user, so no team-less key is ever minted and any lingering one
     * is deactivated.
     */
    private void deactivatePersonalKeys(User user) {
        List<ApiKey> personal =
            apiKeyRepository.findByUserIdAndTeamIdIsNullAndKeyType(user.getId(), ApiKeyType.developer);
        personal.forEach(k -> { k.setIsActive(false); apiKeyRepository.save(k); });
    }

    private void syncTeamMemberships(User user, Set<String> claimNames) {
        Set<String> userLevelRoles = new HashSet<>(props.roles().logosAdmin());
        userLevelRoles.addAll(props.roles().appAdmin());

        Map<Integer, Team> desired = claimNames.stream()
            .filter(r -> !userLevelRoles.contains(r))
            .map(this::resolveTeamForRole)
            .flatMap(Optional::stream)
            .collect(Collectors.toMap(Team::getId, t -> t, (a, b) -> a));

        List<TeamMember> currentKeycloak =
            memberRepository.findById_UserIdAndSource(user.getId(), TeamMemberSource.KEYCLOAK);

        for (TeamMember m : currentKeycloak) {
            if (!desired.containsKey(m.getId().getTeamId())) {
                membershipService.leave(user.getId(), m.getId().getTeamId());
            }
        }
        for (Team team : desired.values()) {
            membershipService.join(user.getId(), team.getId(), false, TeamMemberSource.KEYCLOAK);
        }
    }

    private Optional<Team> resolveTeamForRole(String roleName) {
        Optional<Team> linked = teamRepository.findByKeycloakGroup(roleName);
        if (linked.isPresent()) return linked;
        if (!props.autoProvisionTeams()) return Optional.empty();
        if (!isTeamRole(roleName)) return Optional.empty();
        try {
            return Optional.of(teamAutoProvisioner.findOrCreate(roleName, props.teamRoleSuffixes()));
        } catch (DataIntegrityViolationException e) {
            return teamRepository.findByKeycloakGroup(roleName);
        }
    }

    private boolean isTeamRole(String roleName) {
        return props.teamRoleSuffixes().stream()
            .anyMatch(suffix -> !suffix.isBlank() && roleName.endsWith(suffix));
    }

    public static String deriveTeamName(String roleName, List<String> teamRoleSuffixes) {
        String base = roleName;
        for (String suffix : teamRoleSuffixes) {
            if (!suffix.isBlank() && base.endsWith(suffix)) {
                base = base.substring(0, base.length() - suffix.length());
                break;
            }
        }
        return Arrays.stream(base.split("-"))
            .filter(w -> !w.isEmpty())
            .map(w -> Character.toUpperCase(w.charAt(0)) + w.substring(1))
            .collect(Collectors.joining(" "));
    }
}
