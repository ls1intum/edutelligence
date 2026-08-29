package de.tum.cit.aet.logos.logoswebservice.identity;

import java.nio.charset.StandardCharsets;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.MessageDigest;
import java.security.Signature;
import java.security.spec.ECGenParameterSpec;
import java.security.interfaces.ECPublicKey;
import java.util.Base64;
import java.util.LinkedHashMap;
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
    void register_storesPackedSelfAttestationWithoutDeclaredAlg() throws Exception {
        String challenge = issueChallenge(ALICE_ID, "alice");
        // attStmt.alg is optional; without it the algorithm is derived from
        // the (ES256) credential key.
        Registration registration = buildRegistration(challenge, "new-credential-alg-absent", RP_ID, 0x45,
            AttestationKind.PACKED_SELF, null);

        submitRegistration(ALICE_ID, "alice", registration, null)
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.passkey.credential_id").value(registration.credentialId()));
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
        PACKED_SELF_INVALID_SIGNATURE
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
     * attestations; {@code null} omits the field (it is optional).
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

        Signature signer = Signature.getInstance("SHA256withECDSA");
        signer.initSign(keyPair.getPrivate());
        if (kind == AttestationKind.PACKED_SELF_INVALID_SIGNATURE) {
            // Sign different data: a valid DER signature that does not verify.
            signer.update(concat(authData, sha256("not the clientDataJSON".getBytes(StandardCharsets.UTF_8))));
        } else {
            signer.update(concat(authData, sha256(clientDataJson)));
        }
        byte[] signature = signer.sign();

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
