package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Consumer;
import java.util.function.Function;
import java.util.function.Predicate;
import java.util.function.Supplier;
import java.util.stream.Collectors;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Service;

import de.tum.cit.aet.logos.logoswebservice.identity.dto.KeycloakGroupDirectoryResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.KeycloakGroupOptionDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Team;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.sync.KeycloakAdminClient;

/**
 * The claim names a team can be linked to, read from the realm so an admin can
 * pick one instead of typing it.
 *
 * <p>Both groups and realm roles are offered: {@code KeycloakUserSyncService}
 * resolves a team from any claim name, and the roles are what a realm without
 * groups (such as the development realm) actually carries.
 *
 * <p>The listing is optional — the admin client only exists when
 * {@code logos.auth.sync.enabled=true}, and the realm may be unreachable. Both
 * cases report {@code available=false} rather than failing, so the dialog can
 * fall back to a free-text field.
 */
@Service
public class KeycloakGroupDirectoryService {

    private static final Logger log = LoggerFactory.getLogger(KeycloakGroupDirectoryService.class);
    private static final Duration CACHE_TTL = Duration.ofMinutes(5);

    /** Realm roles every Keycloak realm ships; they name no team. */
    private static final Set<String> BUILT_IN_ROLES = Set.of("offline_access", "uma_authorization");
    private static final String DEFAULT_ROLES_PREFIX = "default-roles-";

    private final ObjectProvider<KeycloakAdminClient> adminClient;
    private final KeycloakGroupLinkNormalizer normalizer;
    private final TeamRepository teamRepository;

    private volatile List<KeycloakGroupOptionDTO> cachedNames = List.of();
    private volatile Instant cachedAt = Instant.EPOCH;

    public KeycloakGroupDirectoryService(ObjectProvider<KeycloakAdminClient> adminClient,
                                         KeycloakGroupLinkNormalizer normalizer,
                                         TeamRepository teamRepository) {
        this.adminClient = adminClient;
        this.normalizer = normalizer;
        this.teamRepository = teamRepository;
    }

    public KeycloakGroupDirectoryResponseDTO list() {
        List<KeycloakGroupOptionDTO> names = claimNames();
        if (names.isEmpty()) {
            return new KeycloakGroupDirectoryResponseDTO(false, List.of());
        }
        Map<String, Team> linkedByGroup = teamRepository.findByKeycloakGroupIsNotNull().stream()
            .collect(Collectors.toMap(Team::getKeycloakGroup, Function.identity(), (a, b) -> a));
        return new KeycloakGroupDirectoryResponseDTO(true, names.stream()
            .map(option -> {
                Team linked = linkedByGroup.get(option.name());
                return linked == null ? option : new KeycloakGroupOptionDTO(
                    option.name(), option.source(), linked.getId(), linked.getName());
            })
            .toList());
    }

    /**
     * The realm's groups and roles, minus the names that can never name a team.
     * Cached briefly: the dialog refetches on every open, while the realm
     * changes rarely and each read is several admin API round trips.
     */
    private List<KeycloakGroupOptionDTO> claimNames() {
        if (Instant.now().isBefore(cachedAt.plus(CACHE_TTL))) return cachedNames;

        KeycloakAdminClient client = adminClient.getIfAvailable();
        if (client == null) return List.of();

        List<KeycloakGroupOptionDTO> options = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        Set<String> reserved = normalizer.reservedNames();

        // Groups and roles are read independently: the service account may be
        // granted one listing and not the other (query-groups without
        // view-realm is the common split), and a deployment that can offer only
        // one of them should still offer that one.
        boolean groupsRead = collect("groups", client::listGroupPaths, name -> isSelectable(name, reserved),
            name -> options.add(new KeycloakGroupOptionDTO(name, "group", null, null)), seen);
        boolean rolesRead = collect("realm roles", client::listRealmRoleNames,
            name -> isSelectable(name, reserved) && !name.startsWith(DEFAULT_ROLES_PREFIX)
                && !BUILT_IN_ROLES.contains(name),
            name -> options.add(new KeycloakGroupOptionDTO(name, "role", null, null)), seen);
        if (!groupsRead && !rolesRead) return List.of();

        options.sort(Comparator.comparing(KeycloakGroupOptionDTO::name, String.CASE_INSENSITIVE_ORDER));
        List<KeycloakGroupOptionDTO> result = List.copyOf(options);
        // Only a complete listing is worth keeping: caching a half of it would
        // hide the other half for the whole TTL after one transient failure,
        // while a permanent one (a service account granted query-groups but not
        // view-realm) costs a cheap retry per request.
        if (groupsRead && rolesRead) {
            cachedNames = result;
            cachedAt = Instant.now();
        }
        return result;
    }

    /** @return whether the listing could be read at all, however empty it was */
    private static boolean collect(String what, Supplier<List<String>> source, Predicate<String> keep,
                                   Consumer<String> sink, Set<String> seen) {
        List<String> names;
        try {
            names = source.get();
        } catch (Exception e) {
            log.warn("Could not read the Keycloak {}: {}", what, e.getMessage());
            return false;
        }
        names.stream().filter(keep).filter(seen::add).forEach(sink);
        return true;
    }

    private static boolean isSelectable(String name, Set<String> reserved) {
        return name != null && !name.isBlank() && !reserved.contains(name);
    }
}
