package de.tum.cit.aet.logos.logoswebservice.identity.sync;

import java.time.Instant;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;

import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakClaimExtractor;
import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakProperties;

@Component
@ConditionalOnProperty(prefix = "logos.auth.sync", name = "enabled", havingValue = "true")
public class KeycloakAdminClient {

    private static final ParameterizedTypeReference<Map<String, Object>> MAP =
        new ParameterizedTypeReference<>() {};
    private static final ParameterizedTypeReference<List<Map<String, Object>>> LIST_OF_MAPS =
        new ParameterizedTypeReference<>() {};

    private final RestClient restClient;
    private final KeycloakProperties props;

    private volatile String cachedToken;
    private volatile Instant tokenExpiry = Instant.EPOCH;

    public KeycloakAdminClient(RestClient.Builder builder, KeycloakProperties props) {
        this.restClient = builder.baseUrl(props.sync().adminBaseUrl()).build();
        this.props = props;
    }

    public Optional<Map<String, Object>> getUser(String keycloakId) {
        try {
            return Optional.ofNullable(restClient.get()
                .uri("/admin/realms/{realm}/users/{id}", props.sync().realm(), keycloakId)
                .header("Authorization", "Bearer " + accessToken())
                .retrieve()
                .body(MAP));
        } catch (HttpClientErrorException.NotFound e) {
            return Optional.empty();
        }
    }

    public Map<String, Map<String, Object>> listUsersById() {
        Map<String, Map<String, Object>> result = new java.util.LinkedHashMap<>();
        int batchSize = 500;
        int first = 0;
        List<Map<String, Object>> page;
        do {
            page = restClient.get()
                .uri("/admin/realms/{realm}/users?first={first}&max={max}",
                    props.sync().realm(), first, batchSize)
                .header("Authorization", "Bearer " + accessToken())
                .retrieve()
                .body(LIST_OF_MAPS);
            if (page != null) {
                page.forEach(u -> {
                    if (u.get("id") instanceof String id) result.put(id, u);
                });
                first += page.size();
            }
        } while (page != null && page.size() == batchSize);
        return result;
    }

    public Set<String> getUserClaimNames(String keycloakId) {
        Set<String> names = new HashSet<>();
        List<Map<String, Object>> roles = restClient.get()
            .uri("/admin/realms/{realm}/users/{id}/role-mappings/realm/composite",
                props.sync().realm(), keycloakId)
            .header("Authorization", "Bearer " + accessToken())
            .retrieve()
            .body(LIST_OF_MAPS);
        if (roles != null) roles.forEach(r -> addName(names, r));

        List<Map<String, Object>> groups = restClient.get()
            .uri("/admin/realms/{realm}/users/{id}/groups", props.sync().realm(), keycloakId)
            .header("Authorization", "Bearer " + accessToken())
            .retrieve()
            .body(LIST_OF_MAPS);
        if (groups != null) groups.forEach(g -> addGroupName(names, g));
        return names;
    }

    private static void addName(Set<String> target, Map<String, Object> rep) {
        if (rep.get("name") instanceof String s) target.add(s);
    }

    private static void addGroupName(Set<String> target, Map<String, Object> rep) {
        if (rep.get("path") instanceof String p) {
            target.add(KeycloakClaimExtractor.normalizeGroupName(p));
        } else if (rep.get("name") instanceof String s) {
            target.add(s);
        }
    }

    private synchronized String accessToken() {
        if (cachedToken != null && Instant.now().isBefore(tokenExpiry.minusSeconds(30))) {
            return cachedToken;
        }
        var form = new LinkedMultiValueMap<String, String>();
        form.add("grant_type", "client_credentials");
        form.add("client_id", props.sync().clientId());
        form.add("client_secret", props.sync().clientSecret());
        Map<String, Object> response = restClient.post()
            .uri("/realms/{realm}/protocol/openid-connect/token", props.sync().realm())
            .contentType(MediaType.APPLICATION_FORM_URLENCODED)
            .body(form)
            .retrieve()
            .body(MAP);
        if (response == null || !(response.get("access_token") instanceof String token) || token.isBlank()) {
            throw new IllegalStateException("Keycloak token endpoint returned no access_token");
        }
        cachedToken = token;
        long expiresIn = ((Number) response.getOrDefault("expires_in", 60)).longValue();
        tokenExpiry = Instant.now().plusSeconds(expiresIn);
        return cachedToken;
    }
}
