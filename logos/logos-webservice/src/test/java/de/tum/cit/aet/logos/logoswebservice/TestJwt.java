package de.tum.cit.aet.logos.logoswebservice;

import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.JwtRequestPostProcessor;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.jwt;

public final class TestJwt {

    private TestJwt() {}

    public static Jwt jwtForSeededUser(int seedId, String username, String... keycloakRoles) {
        Jwt.Builder builder = Jwt.withTokenValue(username + "-token")
            .header("alg", "RS256")
            .subject(String.format("00000000-0000-0000-0000-%012d", seedId))
            .claim("preferred_username", username)
            .claim("given_name", "Test")
            .claim("family_name", "User")
            .claim("email", username + "@test.com");
        if (keycloakRoles.length > 0) {
            builder.claim("realm_access", java.util.Map.of("roles", java.util.List.of(keycloakRoles)));
        }
        return builder.build();
    }

    public static JwtRequestPostProcessor forSeededUser(int seedId, String username, String... keycloakRoles) {
        return jwt().jwt(jwtForSeededUser(seedId, username, keycloakRoles));
    }

    public static JwtRequestPostProcessor testUser() {
        return forSeededUser(1001, "testuser");
    }

    public static Jwt testUserJwt() {
        return jwtForSeededUser(1001, "testuser");
    }

    public static JwtRequestPostProcessor adminUser() {
        return forSeededUser(1002, "adminuser", "chair-member");
    }

    public static Jwt adminJwt() {
        return jwtForSeededUser(1002, "adminuser", "chair-member");
    }

    public static JwtRequestPostProcessor logosAdmin() {
        return forSeededUser(1003, "logosadmin", "itg-admin");
    }

    public static Jwt logosAdminJwt() {
        return jwtForSeededUser(1003, "logosadmin", "itg-admin");
    }
}
