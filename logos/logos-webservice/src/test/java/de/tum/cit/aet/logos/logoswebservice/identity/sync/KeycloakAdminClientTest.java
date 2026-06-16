package de.tum.cit.aet.logos.logoswebservice.identity.sync;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import com.fasterxml.jackson.databind.ObjectMapper;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakProperties;

class KeycloakAdminClientTest {

    private static final String BASE = "http://keycloak-test";
    private static final String REALM = "test-realm";
    private static final String KEYCLOAK_ID = "user-uuid-1";

    private final ObjectMapper om = new ObjectMapper();

    private record Fixture(KeycloakAdminClient client, MockRestServiceServer server) {}

    private Fixture fixture() {
        var builder = RestClient.builder();
        var server = MockRestServiceServer.bindTo(builder).build();
        var props = new KeycloakProperties(
            "logos",
            new KeycloakProperties.Roles(List.of("itg-admin"), List.of("chair-member")),
            5,
            new KeycloakProperties.Sync(false, "0 0 * * * *", BASE, REALM, "logos-sync", "secret"),
            List.of("-dev"), "logos", false);
        return new Fixture(new KeycloakAdminClient(builder, props), server);
    }

    private String json(Object o) throws Exception { return om.writeValueAsString(o); }

    @Test
    void getUser_returnsUserWhenFound() throws Exception {
        var f = fixture();
        f.server().expect(requestTo(BASE + "/realms/" + REALM + "/protocol/openid-connect/token"))
            .andExpect(method(HttpMethod.POST))
            .andRespond(withSuccess(json(Map.of("access_token", "tok1", "expires_in", 300)), MediaType.APPLICATION_JSON));
        f.server().expect(requestTo(BASE + "/admin/realms/" + REALM + "/users/" + KEYCLOAK_ID))
            .andExpect(method(HttpMethod.GET))
            .andExpect(header("Authorization", "Bearer tok1"))
            .andRespond(withSuccess(json(Map.of("id", KEYCLOAK_ID, "username", "alice", "enabled", true)), MediaType.APPLICATION_JSON));

        Optional<Map<String, Object>> result = f.client().getUser(KEYCLOAK_ID);

        assertThat(result).isPresent();
        assertThat(result.get().get("username")).isEqualTo("alice");
        f.server().verify();
    }

    @Test
    void getUser_returnsEmptyWhenNotFound() throws Exception {
        var f = fixture();
        f.server().expect(requestTo(BASE + "/realms/" + REALM + "/protocol/openid-connect/token"))
            .andExpect(method(HttpMethod.POST))
            .andRespond(withSuccess(json(Map.of("access_token", "tok2", "expires_in", 300)), MediaType.APPLICATION_JSON));
        f.server().expect(requestTo(BASE + "/admin/realms/" + REALM + "/users/" + KEYCLOAK_ID))
            .andExpect(method(HttpMethod.GET))
            .andRespond(withStatus(HttpStatus.NOT_FOUND));

        Optional<Map<String, Object>> result = f.client().getUser(KEYCLOAK_ID);

        assertThat(result).isEmpty();
        f.server().verify();
    }

    @Test
    void getUserClaimNames_returnsRoleAndGroupNames() throws Exception {
        var f = fixture();
        f.server().expect(requestTo(BASE + "/realms/" + REALM + "/protocol/openid-connect/token"))
            .andExpect(method(HttpMethod.POST))
            .andRespond(withSuccess(json(Map.of("access_token", "tok3", "expires_in", 300)), MediaType.APPLICATION_JSON));
        f.server().expect(requestTo(BASE + "/admin/realms/" + REALM + "/users/" + KEYCLOAK_ID + "/role-mappings/realm/composite"))
            .andExpect(method(HttpMethod.GET))
            .andRespond(withSuccess(json(List.of(Map.of("name", "app_developer"))), MediaType.APPLICATION_JSON));
        f.server().expect(requestTo(BASE + "/admin/realms/" + REALM + "/users/" + KEYCLOAK_ID + "/groups"))
            .andExpect(method(HttpMethod.GET))
            .andRespond(withSuccess(json(List.of(Map.of("name", "chair-member"))), MediaType.APPLICATION_JSON));

        Set<String> names = f.client().getUserClaimNames(KEYCLOAK_ID);

        assertThat(names).containsExactlyInAnyOrder("app_developer", "chair-member");
        f.server().verify();
    }
}
