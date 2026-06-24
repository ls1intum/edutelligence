package de.tum.cit.aet.logos.logoswebservice.auth;

import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Public, unauthenticated endpoint serving runtime configuration the UI needs
 * before it can initiate login (Keycloak issuer URL and client id). Centralises
 * these values on the server so the web bundle does not have to be rebuilt to
 * point at a different Keycloak instance.
 */
@RestController
public class PublicConfigController {

    private final String issuer;
    private final KeycloakProperties props;

    public PublicConfigController(
            @Value("${spring.security.oauth2.resourceserver.jwt.issuer-uri}") String issuer,
            KeycloakProperties props) {
        this.issuer = issuer;
        this.props = props;
    }

    @GetMapping("/info")
    public ResponseEntity<Map<String, Object>> info() {
        return ResponseEntity.ok(Map.of(
            "keycloak", Map.of(
                "issuer", issuer,
                "client_id", props.clientId()
            )
        ));
    }
}
