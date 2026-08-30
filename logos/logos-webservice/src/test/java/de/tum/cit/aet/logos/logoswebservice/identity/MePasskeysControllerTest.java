package de.tum.cit.aet.logos.logoswebservice.identity;

import java.nio.charset.StandardCharsets;
import java.security.KeyFactory;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.MessageDigest;
import java.security.PrivateKey;
import java.security.Signature;
import java.security.spec.ECGenParameterSpec;
import java.security.spec.PKCS8EncodedKeySpec;
import java.security.interfaces.ECPublicKey;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.upokecenter.cbor.CBORObject;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.context.jdbc.SqlMergeMode;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.ResultActions;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.TestJwt;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestContainersConfig.class)
@TestPropertySource(properties = {
        "spring.liquibase.enabled=true",
        "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml",
        "logos.auth.roles.logos-admin=itg-admin",
        "logos.auth.roles.app-admin=chair-member",
        "logos.auth.sync-debounce-minutes=5",
        // The CORS filter (Spring Security) rejects cross-origin POSTs before
        // they reach the controller unless the origin is allowlisted; the
        // origin-mismatch test needs its evil origin allowed so that the
        // webservice's own clientDataJSON.origin check is what rejects it.
        "logos.cors.allowed-origins=http://localhost,https://evil.example"
})
@Sql(scripts = "/sql/seed-passkeys.sql", executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = "/sql/cleanup-passkeys.sql", executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class MePasskeysControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;

    private static final ObjectMapper JSON = new ObjectMapper();

    // MockMvc's default host; rp-id is unconfigured in the tests, so the
    // webservice derives the relying party id from the request host.
    private static final String ORIGIN = "http://localhost";
    private static final String RP_ID = "localhost";

    // alice (seeded user 1201) authenticates via her Keycloak token.
    private static final int ALICE_ID = 1201;
    private static final int BOB_ID = 1202;

    // Self-signed P-256 attestation certificate (X.509 DER) and its private
    // key (PKCS#8 DER), base64url-free standard base64. fido-u2f requires x5c
    // per WebAuthn L2 §8.6, so the fixture signs with this key instead of the
    // credential key.
    private static final String FIDO_U2F_ATTESTATION_CERT_BASE64 =
        "MIIBnzCCAUWgAwIBAgIUWJHXM/s/4IjFiPpsYOus9dtRyYIwCgYIKoZIzj0EAwIwJTEjMCEGA1UEAwwaTG9nb3MgVTJG"
            + "IFRlc3QgQXR0ZXN0YXRpb24wHhcNMjYwODI5MTE0MzI0WhcNMzYwODI2MTE0MzI0WjAlMSMwIQYDVQQDDBpMb2dv"
            + "cyBVMkYgVGVzdCBBdHRlc3RhdGlvbjBZMBMGByqGSM49AgEGCCqGSM49AwEHA0IABME42oQlWkTWFfdavktUpcmQ"
            + "3yCaBDk5GRzv4WY+1T2thYMJ/g+jM3xSO4eHsJIp2we3QiXpHKgs7bUruWLSoHWjUzBRMB0GA1UdDgQWBBTkgiVU"
            + "GF4Y/MH+1HWJFBT64paAszAfBgNVHSMEGDAWgBTkgiVUGF4Y/MH+1HWJFBT64paAszAPBgNVHRMBAf8EBTADAQH/"
            + "MAoGCCqGSM49BAMCA0gAMEUCIQDTk6SC0jofuf2WblmuoIbL6ZNQrU1xXrR8r1xQ718oNwIgKTRBAR2Yl1Zhx4ce"
            + "foHhZvomQE9uq89RRELl0L6T2BY=";
    private static final String FIDO_U2F_ATTESTATION_KEY_BASE64 =
        "MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgwjoWSipIoODafpHFFPLzAKzjey83nDq4m9X7yQ35jLSh"
            + "RANCAATBONqEJVpE1hX3Wr5LVKXJkN8gmgQ5ORkc7+FmPtU9rYWDCf4PozN8UjuHh7CSKdsHt0Il6RyoLO21K7li0qB1";

    // GET /me/passkeys

    @Test
    void getMyPasskeys_returns401WithNoToken() throws Exception {
        mvc.perform(get("/me/passkeys"))
           .andExpect(status().isUnauthorized());
    }

    @Test
    void getMyPasskeys_returnsOnlyOwnPasskeys() throws Exception {
        mvc.perform(get("/me/passkeys").with(TestJwt.forSeededUser(ALICE_ID, "alice")))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(2))
           .andExpect(jsonPath("$[0].id").value(12101))
           .andExpect(jsonPath("$[0].label").value("Mac - Chrome"))
           .andExpect(jsonPath("$[0].credential_id").value("cGFzc2tleS1hbGljZS0x"))
           .andExpect(jsonPath("$[1].label").value("iPhone - Safari"))
           .andExpect(jsonPath("$[1].credential_id").value("cGFzc2tleS1hbGljZS0y"))
           .andExpect(jsonPath("$[0].created_at").isString());
    }

    // POST /me/passkeys/options

    @Test
    void registrationOptions_returnsChallengeRpAndUser() throws Exception {
        mvc.perform(post("/me/passkeys/options").with(TestJwt.forSeededUser(ALICE_ID, "alice")))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.challenge").isNotEmpty())
           .andExpect(jsonPath("$.rp.id").value(RP_ID))
           .andExpect(jsonPath("$.rp.name").value("Logos"))
           .andExpect(jsonPath("$.user.name").value("alice"))
           .andExpect(jsonPath("$.user.displayName").value("Alice Dev"))
           .andExpect(jsonPath("$.user.id").isNotEmpty())
           .andExpect(jsonPath("$.pubKeyCredParams.length()").value(2))
           .andExpect(jsonPath("$.authenticatorSelection.residentKey").value("required"))
           .andExpect(jsonPath("$.authenticatorSelection.userVerification").value("required"));
    }

    @Test
    void registrationOptions_excludesExistingCredentials() throws Exception {
        mvc.perform(post("/me/passkeys/options").with(TestJwt.forSeededUser(ALICE_ID, "alice")))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.excludeCredentials.length()").value(2))
           .andExpect(jsonPath("$.excludeCredentials[0].id").value("cGFzc2tleS1hbGljZS0x"))
           .andExpect(jsonPath("$.excludeCredentials[1].id").value("cGFzc2tleS1hbGljZS0y"));
    }

    @Test
    void registrationOptions_evictsOldestChallengeBeyondPerUserCap() throws Exception {
        // Five outstanding challenges fill the per-user cap; the sixth issue
        // evicts the first one, which must then be rejected while the newest
        // is still usable.
        List<String> issued = new ArrayList<>();
        for (int i = 0; i < 5; i++) {
            issued.add(issueChallenge(ALICE_ID, "alice"));
        }
        String evicted = issued.get(0);
        issued.add(issueChallenge(ALICE_ID, "alice"));

        Registration stale = buildRegistration(evicted, "new-credential-evicted", RP_ID, 0x45,
            AttestationKind.NONE);
        submitRegistration(ALICE_ID, "alice", stale, null)
            .andExpect(status().isBadRequest());

        Registration fresh = buildRegistration(issued.get(5), "new-credential-fresh", RP_ID, 0x45,
            AttestationKind.NONE);
        submitRegistration(ALICE_ID, "alice", fresh, null)
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.passkey.credential_id").value(fresh.credentialId()));
    }

    // POST /me/passkeys

    @Test
    void register_storesValidPackedSelfAttestation() throws Exception {
        String challenge = issueChallenge(ALICE_ID, "alice");
        Registration registration =
            buildRegistration(challenge, "new-credential-packed", RP_ID, 0x45, AttestationKind.PACKED_SELF);

        submitRegistration(ALICE_ID, "alice", registration, null)
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.result").value("Passkey added"))
            .andExpect(jsonPath("$.passkey.credential_id").value(registration.credentialId()))
            .andExpect(jsonPath("$.passkey.label").value("Test - Chrome"));

        mvc.perform(get("/me/passkeys").with(TestJwt.forSeededUser(ALICE_ID, "alice")))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(3));
    }

    @Test
    void register_rejectsPackedSelfAttestationWithoutDeclaredAlg() throws Exception {
        String challenge = issueChallenge(ALICE_ID, "alice");
        // WebAuthn L2 §8.2 makes attStmt.alg a required member of the packed
        // statement, so a statement without it is rejected — there is no
        // key-type fallback.
        Registration registration = buildRegistration(challenge, "new-credential-alg-absent", RP_ID, 0x45,
            AttestationKind.PACKED_SELF, null);

        submitRegistration(ALICE_ID, "alice", registration, null)
            .andExpect(status().isBadRequest());
    }

    @Test
    void register_rejectsPackedSelfAttestationWithDerEncodedSignature() throws Exception {
        String challenge = issueChallenge(ALICE_ID, "alice");
        // A packed ES256 signature is IEEE P1363 (raw r||s). This fixture
        // signs with ASN.1 DER — a well-formed signature in the wrong
        // encoding, which must be rejected (this is what a plain
        // SHA256withECDSA verifier would wrongly accept).
        Registration registration = buildRegistration(challenge, "new-credential-der-sig", RP_ID, 0x45,
            AttestationKind.PACKED_SELF_DER_SIGNATURE);

        submitRegistration(ALICE_ID, "alice", registration, null)
            .andExpect(status().isBadRequest());
    }

    @Test
    void register_rejectsPackedSelfAttestationWithMismatchedAlg() throws Exception {
        String challenge = issueChallenge(ALICE_ID, "alice");
        // attStmt.alg declares RS256, but the credential key is ES256.
        Registration registration = buildRegistration(challenge, "new-credential-alg-mismatch", RP_ID, 0x45,
            AttestationKind.PACKED_SELF, -257);

        submitRegistration(ALICE_ID, "alice", registration, null)
            .andExpect(status().isBadRequest());
    }

    @Test
    void register_rejectsPackedSelfAttestationWithUnsupportedAlg() throws Exception {
        String challenge = issueChallenge(ALICE_ID, "alice");
        // ES384 is a valid WebAuthn algorithm but outside the supported set
        // (ES256/RS256).
        Registration registration = buildRegistration(challenge, "new-credential-alg-unsupported", RP_ID, 0x45,
            AttestationKind.PACKED_SELF, -35);

        submitRegistration(ALICE_ID, "alice", registration, null)
            .andExpect(status().isBadRequest());
    }

    @Test
    void register_storesValidFidoU2fAttestation() throws Exception {
        String challenge = issueChallenge(ALICE_ID, "alice");
        // x5c carries the self-signed P-256 attestation certificate; sig is
        // its key's signature over the U2F registration response data.
        Registration registration =
            buildRegistration(challenge, "new-credential-u2f", RP_ID, 0x45, AttestationKind.FIDO_U2F);

        submitRegistration(ALICE_ID, "alice", registration, null)
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.passkey.credential_id").value(registration.credentialId()));
    }

    @Test
    void register_rejectsFidoU2fWithoutX5c() throws Exception {
        String challenge = issueChallenge(ALICE_ID, "alice");
        // WebAuthn L2 §8.6 makes x5c mandatory for the fido-u2f format —
        // there is no self-attestation path for it.
        Registration registration =
            buildRegistration(challenge, "new-credential-u2f-nocert", RP_ID, 0x45,
                AttestationKind.FIDO_U2F_WITHOUT_X5C);

        submitRegistration(ALICE_ID, "alice", registration, null)
            .andExpect(status().isBadRequest());
    }

    @Test
    void register_storesValidNoneAttestation() throws Exception {
        String challenge = issueChallenge(ALICE_ID, "alice");
        Registration registration =
            buildRegistration(challenge, "new-credential-none", RP_ID, 0x45, AttestationKind.NONE);

        submitRegistration(ALICE_ID, "alice", registration, null)
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.passkey.credential_id").value(registration.credentialId()));
    }

    @Test
    void register_rejectsTamperedAttestationSignature() throws Exception {
        String challenge = issueChallenge(ALICE_ID, "alice");
        Registration registration = buildRegistration(challenge, "new-credential-bad-sig", RP_ID, 0x45,
            AttestationKind.PACKED_SELF_INVALID_SIGNATURE);

        submitRegistration(ALICE_ID, "alice", registration, null)
            .andExpect(status().isBadRequest());
    }

    @Test
    void register_rejectsUnknownChallenge() throws Exception {
        Registration registration = buildRegistration("bm90LWlzc3VlZA", "new-credential-unknown",
            RP_ID, 0x45, AttestationKind.NONE);

        submitRegistration(ALICE_ID, "alice", registration, null)
            .andExpect(status().isBadRequest());
    }

    @Test
    void register_rejectsChallengeIssuedToAnotherUser() throws Exception {
        String challenge = issueChallenge(ALICE_ID, "alice");
        Registration registration = buildRegistration(challenge, "new-credential-cross-user",
            RP_ID, 0x45, AttestationKind.NONE);

        submitRegistration(BOB_ID, "bob", registration, null)
            .andExpect(status().isBadRequest());
    }

    @Test
    void register_keepsChallengeUsableByOwnerAfterRejectingAnotherUser() throws Exception {
        // Bob submits a registration carrying alice's challenge. The
        // ownership check must fail before the challenge is consumed, so
        // alice's in-flight registration still works with the same challenge.
        String challenge = issueChallenge(ALICE_ID, "alice");
        Registration registration = buildRegistration(challenge, "new-credential-ownership",
            RP_ID, 0x45, AttestationKind.NONE);

        submitRegistration(BOB_ID, "bob", registration, null)
            .andExpect(status().isBadRequest());

        submitRegistration(ALICE_ID, "alice", registration, null)
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.passkey.credential_id").value(registration.credentialId()));
    }

    @Test
    void register_rejectsOriginMismatch() throws Exception {
        String challenge = issueChallenge(ALICE_ID, "alice");
        Registration registration =
            buildRegistration(challenge, "new-credential-origin", RP_ID, 0x45, AttestationKind.NONE);
        Map<String, String> body = registrationBody(registration, null);
        body.remove("label");

        mvc.perform(post("/me/passkeys")
                .with(TestJwt.forSeededUser(ALICE_ID, "alice"))
                .header("Origin", "https://evil.example")
                .contentType(MediaType.APPLICATION_JSON)
                .content(JSON.writeValueAsString(body)))
           .andExpect(status().isBadRequest());
    }

    @Test
    void register_rejectsMissingUserVerificationFlag() throws Exception {
        String challenge = issueChallenge(ALICE_ID, "alice");
        // 0x41: User Present + attested credential, but no User Verified.
        Registration registration =
            buildRegistration(challenge, "new-credential-no-uv", RP_ID, 0x41, AttestationKind.NONE);

        submitRegistration(ALICE_ID, "alice", registration, null)
            .andExpect(status().isBadRequest());
    }

    @Test
    void register_rejectsWrongRelyingParty() throws Exception {
        String challenge = issueChallenge(ALICE_ID, "alice");
        Registration registration =
            buildRegistration(challenge, "new-credential-wrong-rp", "evil.example", 0x45, AttestationKind.NONE);

        submitRegistration(ALICE_ID, "alice", registration, null)
            .andExpect(status().isBadRequest());
    }

    @Test
    void register_rejectsCredentialIdMismatch() throws Exception {
        String challenge = issueChallenge(ALICE_ID, "alice");
        Registration registration =
            buildRegistration(challenge, "new-credential-mismatch", RP_ID, 0x45, AttestationKind.NONE);

        submitRegistration(ALICE_ID, "alice", registration, "b3RoZXItY3JlZGVudGlhbA")
            .andExpect(status().isBadRequest());
    }

    @Test
    void register_rejectsUnsupportedCoseKeyWithNoneAttestation() throws Exception {
        String challenge = issueChallenge(ALICE_ID, "alice");
        // An OKP (Ed25519) COSE key is outside the supported set (ES256/RS256).
        // It must be rejected even though the "none" format carries no signature
        // to check against — the key bytes are persisted, so they are validated
        // unconditionally.
        CBORObject unsupportedKey = CBORObject.NewMap();
        unsupportedKey.Add(1, 1); // kty: OKP
        unsupportedKey.Add(-1, 6); // crv: Ed25519
        unsupportedKey.Add(3, -8); // alg: EdDSA
        unsupportedKey.Add(-2, CBORObject.FromObject(new byte[32]));

        Registration registration = buildNoneRegistrationWithCose(
            challenge, "new-credential-badkey", RP_ID, 0x45, unsupportedKey);

        submitRegistration(ALICE_ID, "alice", registration, null)
            .andExpect(status().isBadRequest());
    }

    @Test
    void register_rejectsMissingFields() throws Exception {
        mvc.perform(post("/me/passkeys")
                .with(TestJwt.forSeededUser(ALICE_ID, "alice"))
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"credentialId\": \"Y2lk\"}"))
           .andExpect(status().isBadRequest());
    }

    @Test
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    @Sql(statements = "INSERT INTO user_passkeys (id, user_id, credential_id, public_key, sign_count, label, created_at) "
        + "VALUES (12109, 1201, 'cGFzc2tleS1kdXA', '\\x09', 0, 'Duplicate', NOW())")
    void register_rejectsDuplicateCredential() throws Exception {
        String challenge = issueChallenge(ALICE_ID, "alice");
        Registration registration =
            buildRegistration(challenge, "passkey-dup", RP_ID, 0x45, AttestationKind.NONE);

        submitRegistration(ALICE_ID, "alice", registration, null)
            .andExpect(status().isConflict());
    }

    @Test
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    @Sql(statements = "INSERT INTO user_passkeys (id, user_id, credential_id, public_key, sign_count, label, created_at) "
        + "VALUES (12110, 1201, 'cGFzc2tleS1jcm9zcy11c2VyLWR1cA', '\\x09', 0, 'Cross-user', NOW())")
    void register_rejectsCredentialAlreadyRegisteredToAnotherUser() throws Exception {
        String challenge = issueChallenge(BOB_ID, "bob");
        Registration registration =
            buildRegistration(challenge, "passkey-cross-user-dup", RP_ID, 0x45, AttestationKind.NONE);

        submitRegistration(BOB_ID, "bob", registration, null)
            .andExpect(status().isConflict());
    }

    // Per-user passkey cap (10). alice has 2 seeded passkeys, so the
    // boundary tests seed up to 9 and 10.

    @Test
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    @Sql(statements = """
        INSERT INTO user_passkeys (id, user_id, credential_id, public_key, sign_count, label, created_at) VALUES (12111, 1201, 'cGFzc2tleS1jYXAtMQ', '\\x09', 0, 'Cap 3', NOW());
        INSERT INTO user_passkeys (id, user_id, credential_id, public_key, sign_count, label, created_at) VALUES (12112, 1201, 'cGFzc2tleS1jYXAtMg', '\\x09', 0, 'Cap 4', NOW());
        INSERT INTO user_passkeys (id, user_id, credential_id, public_key, sign_count, label, created_at) VALUES (12113, 1201, 'cGFzc2tleS1jYXAtMw', '\\x09', 0, 'Cap 5', NOW());
        INSERT INTO user_passkeys (id, user_id, credential_id, public_key, sign_count, label, created_at) VALUES (12114, 1201, 'cGFzc2tleS1jYXAtNA', '\\x09', 0, 'Cap 6', NOW());
        INSERT INTO user_passkeys (id, user_id, credential_id, public_key, sign_count, label, created_at) VALUES (12115, 1201, 'cGFzc2tleS1jYXAtNQ', '\\x09', 0, 'Cap 7', NOW());
        INSERT INTO user_passkeys (id, user_id, credential_id, public_key, sign_count, label, created_at) VALUES (12116, 1201, 'cGFzc2tleS1jYXAtNg', '\\x09', 0, 'Cap 8', NOW());
        INSERT INTO user_passkeys (id, user_id, credential_id, public_key, sign_count, label, created_at) VALUES (12117, 1201, 'cGFzc2tleS1jYXAtNw', '\\x09', 0, 'Cap 9', NOW());
        """)
    void register_allowsRegistrationUpToPerUserCap() throws Exception {
        // 2 seeded + 7 here = 9, one below the cap of 10: the 10th
        // registration is still allowed.
        String challenge = issueChallenge(ALICE_ID, "alice");
        Registration registration =
            buildRegistration(challenge, "passkey-cap-boundary", RP_ID, 0x45, AttestationKind.NONE);

        submitRegistration(ALICE_ID, "alice", registration, null)
            .andExpect(status().isOk());
    }

    @Test
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    @Sql(statements = """
        INSERT INTO user_passkeys (id, user_id, credential_id, public_key, sign_count, label, created_at) VALUES (12118, 1201, 'cGFzc2tleS1jYXAtOA', '\\x09', 0, 'Cap 10', NOW());
        INSERT INTO user_passkeys (id, user_id, credential_id, public_key, sign_count, label, created_at) VALUES (12119, 1201, 'cGFzc2tleS1jYXAtOQ', '\\x09', 0, 'Cap 11', NOW());
        INSERT INTO user_passkeys (id, user_id, credential_id, public_key, sign_count, label, created_at) VALUES (12120, 1201, 'cGFzc2tleS1jYXAtMTA', '\\x09', 0, 'Cap 12', NOW());
        INSERT INTO user_passkeys (id, user_id, credential_id, public_key, sign_count, label, created_at) VALUES (12121, 1201, 'cGFzc2tleS1jYXAtMTE', '\\x09', 0, 'Cap 13', NOW());
        INSERT INTO user_passkeys (id, user_id, credential_id, public_key, sign_count, label, created_at) VALUES (12122, 1201, 'cGFzc2tleS1jYXAtMTI', '\\x09', 0, 'Cap 14', NOW());
        INSERT INTO user_passkeys (id, user_id, credential_id, public_key, sign_count, label, created_at) VALUES (12123, 1201, 'cGFzc2tleS1jYXAtMTM', '\\x09', 0, 'Cap 15', NOW());
        INSERT INTO user_passkeys (id, user_id, credential_id, public_key, sign_count, label, created_at) VALUES (12124, 1201, 'cGFzc2tleS1jYXAtMTQ', '\\x09', 0, 'Cap 16', NOW());
        INSERT INTO user_passkeys (id, user_id, credential_id, public_key, sign_count, label, created_at) VALUES (12125, 1201, 'cGFzc2tleS1jYXAtMTU', '\\x09', 0, 'Cap 17', NOW());
        """)
    void register_rejectsRegistrationBeyondPerUserCap() throws Exception {
        // 2 seeded + 8 here = the cap of 10 already reached.
        String challenge = issueChallenge(ALICE_ID, "alice");
        Registration registration =
            buildRegistration(challenge, "passkey-cap-exceeded", RP_ID, 0x45, AttestationKind.NONE);

        submitRegistration(ALICE_ID, "alice", registration, null)
            .andExpect(status().isConflict())
            .andExpect(jsonPath("$.detail").value(
                "This account already has the maximum of 10 passkeys. Remove one first."));
    }

    // DELETE /me/passkeys/{id}

    @Test
    void delete_deletesOwnPasskey() throws Exception {
        mvc.perform(delete("/me/passkeys/12101").with(TestJwt.forSeededUser(ALICE_ID, "alice")))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Passkey deleted"));

        mvc.perform(get("/me/passkeys").with(TestJwt.forSeededUser(ALICE_ID, "alice")))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(1))
           .andExpect(jsonPath("$[0].id").value(12102));
    }

    @Test
    void delete_returns404ForUnknown() throws Exception {
        mvc.perform(delete("/me/passkeys/999999").with(TestJwt.forSeededUser(ALICE_ID, "alice")))
           .andExpect(status().isNotFound());
    }

    @Test
    void delete_returns403WhenNotOwner() throws Exception {
        mvc.perform(delete("/me/passkeys/12101").with(TestJwt.forSeededUser(BOB_ID, "bob")))
           .andExpect(status().isForbidden());
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    private String issueChallenge(int userId, String username) throws Exception {
        MvcResult result = mvc.perform(post("/me/passkeys/options")
                .with(TestJwt.forSeededUser(userId, username)))
            .andExpect(status().isOk())
            .andReturn();
        return JSON.readTree(result.getResponse().getContentAsString()).get("challenge").asText();
    }

    private ResultActions submitRegistration(int userId, String username, Registration registration,
            String credentialIdOverride) throws Exception {
        return mvc.perform(post("/me/passkeys")
            .with(TestJwt.forSeededUser(userId, username))
            .header("Origin", ORIGIN)
            .contentType(MediaType.APPLICATION_JSON)
            .content(JSON.writeValueAsString(registrationBody(registration, credentialIdOverride))));
    }

    private Map<String, String> registrationBody(Registration registration, String credentialIdOverride) {
        Map<String, String> body = new LinkedHashMap<>();
        body.put("credentialId", credentialIdOverride != null ? credentialIdOverride : registration.credentialId());
        body.put("clientDataJSON", registration.clientDataJson());
        body.put("attestationObject", registration.attestationObject());
        body.put("challenge", registration.challenge());
        body.put("label", "Test - Chrome");
        return body;
    }

    /** Which attestation format the fixture's attestationObject carries. */
    private enum AttestationKind {
        NONE,
        PACKED_SELF,
        PACKED_SELF_INVALID_SIGNATURE,
        // A well-formed packed signature in the wrong (DER) encoding.
        PACKED_SELF_DER_SIGNATURE,
        FIDO_U2F,
        FIDO_U2F_WITHOUT_X5C
    }

    /** A complete, internally consistent WebAuthn registration response. */
    private record Registration(String credentialId, String clientDataJson, String attestationObject,
                                String challenge) {}

    private static Registration buildRegistration(String challenge, String credentialIdText, String rpId,
            int flags, AttestationKind kind) throws Exception {
        // Browsers declare the attestation algorithm; the default mirrors that.
        return buildRegistration(challenge, credentialIdText, rpId, flags, kind, -7);
    }

    /**
     * As {@link #buildRegistration}, with a declared attStmt.alg for the packed
     * attestations; {@code null} omits the field (a spec violation per WebAuthn
     * L2 §8.2 — used by the rejection test).
     */
    private static Registration buildRegistration(String challenge, String credentialIdText, String rpId,
            int flags, AttestationKind kind, Integer attStmtAlg) throws Exception {
        byte[] credentialId = credentialIdText.getBytes(StandardCharsets.UTF_8);

        KeyPairGenerator generator = KeyPairGenerator.getInstance("EC");
        generator.initialize(new ECGenParameterSpec("secp256r1"));
        KeyPair keyPair = generator.generateKeyPair();
        ECPublicKey publicKey = (ECPublicKey) keyPair.getPublic();

        // COSE key for the freshly generated ES256 key.
        CBORObject coseKey = CBORObject.NewMap();
        coseKey.Add(1, 2); // kty: EC2
        coseKey.Add(-1, 1); // crv: P-256
        coseKey.Add(3, -7); // alg: ES256
        coseKey.Add(-2, CBORObject.FromObject(fixed32(publicKey.getW().getAffineX())));
        coseKey.Add(-3, CBORObject.FromObject(fixed32(publicKey.getW().getAffineY())));
        byte[] coseKeyBytes = coseKey.EncodeToBytes();

        // authData: rpIdHash(32) | flags(1) | signCount(4) | AAGUID(16) |
        //           credIdLen(2) | credId | COSE key
        byte[] authData = new byte[37 + 16 + 2 + credentialId.length + coseKeyBytes.length];
        System.arraycopy(sha256(rpId.getBytes(StandardCharsets.UTF_8)), 0, authData, 0, 32);
        authData[32] = (byte) flags;
        int offset = 53;
        authData[offset] = (byte) (credentialId.length >>> 8);
        authData[offset + 1] = (byte) credentialId.length;
        System.arraycopy(credentialId, 0, authData, offset + 2, credentialId.length);
        System.arraycopy(coseKeyBytes, 0, authData, offset + 2 + credentialId.length, coseKeyBytes.length);

        Map<String, String> clientData = new LinkedHashMap<>();
        clientData.put("type", "webauthn.create");
        clientData.put("challenge", challenge);
        clientData.put("origin", ORIGIN);
        byte[] clientDataJson = JSON.writeValueAsBytes(clientData);

        byte[] signature;
        if (kind == AttestationKind.FIDO_U2F || kind == AttestationKind.FIDO_U2F_WITHOUT_X5C) {
            // FIDO U2F signs 0x00 || rpIdHash || clientDataHash || credentialId
            // || publicKeyU2F (WebAuthn L2 §8.6) with the attestation
            // certificate key, not the credential key.
            byte[] upk = new byte[65];
            upk[0] = 0x04;
            System.arraycopy(fixed32(publicKey.getW().getAffineX()), 0, upk, 1, 32);
            System.arraycopy(fixed32(publicKey.getW().getAffineY()), 0, upk, 33, 32);
            byte[] u2fSignedData = new byte[1 + 32 + 32 + credentialId.length + upk.length];
            int u2fOffset = 0;
            u2fSignedData[u2fOffset++] = 0x00;
            System.arraycopy(sha256(rpId.getBytes(StandardCharsets.UTF_8)), 0, u2fSignedData, u2fOffset, 32);
            u2fOffset += 32;
            System.arraycopy(sha256(clientDataJson), 0, u2fSignedData, u2fOffset, 32);
            u2fOffset += 32;
            System.arraycopy(credentialId, 0, u2fSignedData, u2fOffset, credentialId.length);
            u2fOffset += credentialId.length;
            System.arraycopy(upk, 0, u2fSignedData, u2fOffset, upk.length);
            Signature u2fSigner = Signature.getInstance("SHA256withECDSA");
            u2fSigner.initSign(u2fAttestationKey());
            u2fSigner.update(u2fSignedData);
            signature = u2fSigner.sign();
        } else {
            // A packed ES256 signature is IEEE P1363 (raw r||s) per COSE /
            // WebAuthn L2 — not the DER encoding plain SHA256withECDSA
            // produces. Signing with the P1363 variant is what makes the
            // test exercise the verifier's encoding choice instead of
            // confirming it against itself (the U2F branch above keeps DER,
            // which is correct for FIDO U2F).
            boolean der = kind == AttestationKind.PACKED_SELF_DER_SIGNATURE;
            Signature signer =
                Signature.getInstance(der ? "SHA256withECDSA" : "SHA256withECDSAinP1363Format");
            signer.initSign(keyPair.getPrivate());
            if (kind == AttestationKind.PACKED_SELF_INVALID_SIGNATURE) {
                // Sign different data: a valid P1363 signature that does not verify.
                signer.update(concat(authData, sha256("not the clientDataJSON".getBytes(StandardCharsets.UTF_8))));
            } else {
                signer.update(concat(authData, sha256(clientDataJson)));
            }
            signature = signer.sign();
        }

        // attestationObject / attStmt use TEXT keys (WebAuthn L2 §6.2); only
        // the COSE key above uses integer labels.
        CBORObject attStmt = CBORObject.NewMap();
        CBORObject attestationObject = CBORObject.NewMap();
        switch (kind) {
            case NONE -> attestationObject.Add("fmt", "none");
            case PACKED_SELF, PACKED_SELF_INVALID_SIGNATURE -> {
                if (attStmtAlg != null) {
                    attStmt.Add("alg", attStmtAlg);
                }
                attStmt.Add("sig", CBORObject.FromObject(signature));
                attestationObject.Add("fmt", "packed");
            }
            case FIDO_U2F, FIDO_U2F_WITHOUT_X5C -> {
                if (kind == AttestationKind.FIDO_U2F) {
                    attStmt.Add("x5c", CBORObject.NewArray()
                        .Add(CBORObject.FromObject(
                            Base64.getDecoder().decode(FIDO_U2F_ATTESTATION_CERT_BASE64))));
                }
                attStmt.Add("sig", CBORObject.FromObject(signature));
                attestationObject.Add("fmt", "fido-u2f");
            }
        }
        attestationObject.Add("attStmt", attStmt);
        attestationObject.Add("authData", CBORObject.FromObject(authData));

        return new Registration(
            base64Url(credentialId),
            base64Url(clientDataJson),
            base64Url(attestationObject.EncodeToBytes()),
            challenge);
    }

    /**
     * A {@code none}-attestation registration carrying an arbitrary COSE key,
     * for key-validation tests (the attestation format is irrelevant to COSE
     * key validation, which happens unconditionally).
     */
    private static Registration buildNoneRegistrationWithCose(String challenge, String credentialIdText,
            String rpId, int flags, CBORObject coseKey) throws Exception {
        byte[] credentialId = credentialIdText.getBytes(StandardCharsets.UTF_8);
        byte[] coseKeyBytes = coseKey.EncodeToBytes();

        byte[] authData = new byte[37 + 16 + 2 + credentialId.length + coseKeyBytes.length];
        System.arraycopy(sha256(rpId.getBytes(StandardCharsets.UTF_8)), 0, authData, 0, 32);
        authData[32] = (byte) flags;
        int offset = 53;
        authData[offset] = (byte) (credentialId.length >>> 8);
        authData[offset + 1] = (byte) credentialId.length;
        System.arraycopy(credentialId, 0, authData, offset + 2, credentialId.length);
        System.arraycopy(coseKeyBytes, 0, authData, offset + 2 + credentialId.length, coseKeyBytes.length);

        Map<String, String> clientData = new LinkedHashMap<>();
        clientData.put("type", "webauthn.create");
        clientData.put("challenge", challenge);
        clientData.put("origin", ORIGIN);
        byte[] clientDataJson = JSON.writeValueAsBytes(clientData);

        // TEXT keys for the attestationObject (WebAuthn L2 §6.2); the COSE key
        // inside authData still uses integer labels.
        CBORObject attestationObject = CBORObject.NewMap();
        attestationObject.Add("fmt", "none");
        attestationObject.Add("attStmt", CBORObject.NewMap());
        attestationObject.Add("authData", CBORObject.FromObject(authData));

        return new Registration(
            base64Url(credentialId),
            base64Url(clientDataJson),
            base64Url(attestationObject.EncodeToBytes()),
            challenge);
    }

    /** Big-endian 32-byte representation of an EC coordinate (leading zero kept). */
    private static byte[] fixed32(java.math.BigInteger value) {
        byte[] bytes = value.toByteArray();
        byte[] result = new byte[32];
        if (bytes.length <= 32) {
            System.arraycopy(bytes, 0, result, 32 - bytes.length, bytes.length);
        } else {
            // Leading zero byte from the positive sign; drop it.
            System.arraycopy(bytes, bytes.length - 32, result, 0, 32);
        }
        return result;
    }

    private static PrivateKey u2fAttestationKey() throws Exception {
        return KeyFactory.getInstance("EC").generatePrivate(new PKCS8EncodedKeySpec(
            Base64.getDecoder().decode(FIDO_U2F_ATTESTATION_KEY_BASE64)));
    }

    private static byte[] sha256(byte[] input) throws Exception {
        return MessageDigest.getInstance("SHA-256").digest(input);
    }

    private static byte[] concat(byte[] a, byte[] b) {
        byte[] result = new byte[a.length + b.length];
        System.arraycopy(a, 0, result, 0, a.length);
        System.arraycopy(b, 0, result, a.length, b.length);
        return result;
    }

    private static String base64Url(byte[] bytes) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }
}
