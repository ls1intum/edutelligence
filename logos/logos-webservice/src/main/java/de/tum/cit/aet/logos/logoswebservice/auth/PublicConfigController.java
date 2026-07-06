package de.tum.cit.aet.logos.logoswebservice.auth;

import java.util.LinkedHashMap;
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
    private final String passkeyRpId;
    private final String passkeyRpName;
    private final KeycloakProperties props;

    public PublicConfigController(
            @Value("${spring.security.oauth2.resourceserver.jwt.issuer-uri}") String issuer,
            @Value("${logos.auth.passkey.rp-id:}") String passkeyRpId,
            @Value("${logos.auth.passkey.rp-name:Logos}") String passkeyRpName,
            KeycloakProperties props) {
        this.issuer = issuer;
        this.passkeyRpId = passkeyRpId;
        this.passkeyRpName = passkeyRpName;
        this.props = props;
    }

    @GetMapping("/info")
    public ResponseEntity<Map<String, Object>> info() {
        Map<String, Object> keycloak = new LinkedHashMap<>();
        keycloak.put("issuer", issuer);
        keycloak.put("client_id", props.clientId());
        // WebAuthn Relying Party ID for passkeys. Blank => the UI falls back to the
        // current hostname; on the shared TUM Keycloak this must be the parent
        // domain (e.g. aet.cit.tum.de) so passkeys are shared across subdomains.
        keycloak.put("passkey_rp_id", passkeyRpId);
        keycloak.put("passkey_rp_name", passkeyRpName);
        return ResponseEntity.ok(Map.of("keycloak", keycloak));
    }
}
