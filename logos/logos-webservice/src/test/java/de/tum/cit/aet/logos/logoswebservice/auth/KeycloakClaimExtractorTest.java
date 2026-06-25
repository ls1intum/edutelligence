package de.tum.cit.aet.logos.logoswebservice.auth;

import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.security.oauth2.jwt.Jwt;
import static org.assertj.core.api.Assertions.assertThat;

class KeycloakClaimExtractorTest {

    private final KeycloakProperties props = new KeycloakProperties(
        "logos",
        new KeycloakProperties.Roles(List.of("itg-admin"), List.of("chair-member")),
        5,
        new KeycloakProperties.Sync(false, "", "", "tum", "logos-sync", ""),
        List.of("-dev"), "logos", false);

    private final KeycloakClaimExtractor extractor = new KeycloakClaimExtractor(props);

    private Jwt.Builder baseJwt() {
        return Jwt.withTokenValue("token")
            .header("alg", "RS256")
            .subject("11111111-1111-1111-1111-111111111111")
            .claim("preferred_username", "alice")
            .claim("given_name", "Alice")
            .claim("family_name", "Artemis")
            .claim("email", "alice@tum.de");
    }

    @Test
    void extractsIdentityFields() {
        KeycloakClaims claims = extractor.extract(baseJwt().build());
        assertThat(claims.keycloakId()).isEqualTo("11111111-1111-1111-1111-111111111111");
        assertThat(claims.username()).isEqualTo("alice");
        assertThat(claims.prename()).isEqualTo("Alice");
        assertThat(claims.name()).isEqualTo("Artemis");
        assertThat(claims.email()).isEqualTo("alice@tum.de");
    }

    @Test
    void collectsRealmRolesClientRolesAndGroups() {
        Jwt jwt = baseJwt()
            .claim("realm_access", Map.of("roles", List.of("artemis-dev", "offline_access")))
            .claim("resource_access", Map.of("logos", Map.of("roles", List.of("chair-member"))))
            .claim("groups", List.of("/helios-dev"))
            .build();
        KeycloakClaims claims = extractor.extract(jwt);
        assertThat(claims.roleNames())
            .containsExactlyInAnyOrder("artemis-dev", "offline_access", "chair-member", "helios-dev");
    }

    @Test
    void missingClaimsYieldEmptyRoleSetAndNullUsername() {
        Jwt jwt = Jwt.withTokenValue("token").header("alg", "RS256")
            .subject("22222222-2222-2222-2222-222222222222").build();
        KeycloakClaims claims = extractor.extract(jwt);
        assertThat(claims.roleNames()).isEmpty();
        assertThat(claims.username()).isNull();
        assertThat(claims.prename()).isEmpty();
        assertThat(claims.name()).isEmpty();
    }
}
