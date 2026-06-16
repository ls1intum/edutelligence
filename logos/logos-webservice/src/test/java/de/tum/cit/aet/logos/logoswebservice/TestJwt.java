package de.tum.cit.aet.logos.logoswebservice;

import org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.JwtRequestPostProcessor;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.jwt;

public final class TestJwt {

    private TestJwt() {}

    public static JwtRequestPostProcessor forSeededUser(int seedId, String username, String... keycloakRoles) {
        return jwt().jwt(j -> {
            j.subject(String.format("00000000-0000-0000-0000-%012d", seedId))
                .claim("preferred_username", username)
                .claim("given_name", "Test")
                .claim("family_name", "User")
                .claim("email", username + "@test.com");
            if (keycloakRoles.length > 0) {
                j.claim("realm_access", java.util.Map.of("roles", java.util.List.of(keycloakRoles)));
            }
        });
    }

    public static JwtRequestPostProcessor testUser() {
        return forSeededUser(1001, "testuser");
    }

    public static JwtRequestPostProcessor adminUser() {
        return jwt().jwt(j -> j
            .subject("00000000-0000-0000-0000-000000001002")
            .claim("given_name", "Admin")
            .claim("family_name", "User")
            .claim("email", "admin@test.com")
            .claim("realm_access", java.util.Map.of("roles", java.util.List.of("chair-member"))));
    }

    public static JwtRequestPostProcessor logosAdmin() {
        return forSeededUser(1003, "logosadmin", "itg-admin");
    }
}
