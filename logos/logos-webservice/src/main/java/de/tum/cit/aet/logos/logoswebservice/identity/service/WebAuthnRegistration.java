package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.io.ByteArrayInputStream;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.security.AlgorithmParameters;
import java.security.GeneralSecurityException;
import java.security.InvalidKeyException;
import java.security.KeyFactory;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.PublicKey;
import java.security.Signature;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.security.spec.ECGenParameterSpec;
import java.security.spec.ECParameterSpec;
import java.security.spec.ECPoint;
import java.security.spec.ECPublicKeySpec;
import java.security.spec.RSAPublicKeySpec;
import java.util.Arrays;
import java.util.Base64;
import java.util.Map;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.upokecenter.cbor.CBORException;
import com.upokecenter.cbor.CBORObject;
import com.upokecenter.cbor.CBORType;

/**
 * Verifies WebAuthn registration (attestation) responses, following the
 * verification steps of WebAuthn Level 2, section 7.1.
 *
 * <p>The checks performed are: clientDataJSON (type, challenge, origin), the
 * relying party hash in authData, the User Present / User Verified flags, the
 * attested credential data (credential id must match the one in the request,
 * COSE public key must be well-formed and use a supported algorithm) and the
 * attestation statement. Supported attestation formats are {@code none} (no
 * signature — the credential key binding is then proven at first use),
 * {@code packed} (self-attestation or certificate-based, honoring the
 * optional attStmt.alg) and {@code fido-u2f} (certificate-based; x5c is
 * required by the format).
 *
 * <p>Attestation certificate chains are not checked against a trust anchor
 * (FIDO MDS): the signature is verified against the leaf certificate, which
 * proves the authenticator produced it. For this deployment — users managing
 * their own personal passkeys — that is the assurance we need; the credential
 * key signature check is what prevents a forged registration.
 */
public final class WebAuthnRegistration {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    /** P-256 (secp256r1) — the only EC curve we accept. */
    private static final ECParameterSpec P256;

    static {
        try {
            AlgorithmParameters parameters = AlgorithmParameters.getInstance("EC");
            parameters.init(new ECGenParameterSpec("secp256r1"));
            P256 = parameters.getParameterSpec(ECParameterSpec.class);
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException("P-256 unavailable", e);
        }
    }

    /**
     * Upper bound for the COSE key bytes persisted as the public key. A
     * legitimate ES256 key is ~50 bytes and RS256 ~180; even an oversized
     * RSA key is well under this. The cap stops unbounded CBOR from being
     * stored for the {@code none} format, whose attestation carries no key
     * signature to check against.
     */
    private static final int MAX_PUBLIC_KEY_BYTES = 1024;

    private WebAuthnRegistration() {}

    /** Verified content of a registration response. */
    public record Result(
        byte[] credentialId,
        String credentialIdBase64Url,
        byte[] publicKeyCose,
        long signCount) {}

    /**
     * Verifies a registration response.
     *
     * @param credentialId        the credential id the client reports (raw bytes)
     * @param clientDataJson      the clientDataJSON exactly as created by the client
     * @param attestationObject   the attestationObject exactly as created by the client
     * @param expectedChallenge   the challenge issued by {@link PasskeyChallengeStore} (raw bytes)
     * @param expectedOrigin      origin the registration must have happened in
     * @param rpId                relying party id this server registers for
     * @return the verified credential data
     * @throws IllegalArgumentException when any check fails
     */
    public static Result verify(byte[] credentialId, byte[] clientDataJson, byte[] attestationObject,
                                byte[] expectedChallenge, String expectedOrigin, String rpId) {
        // 1. clientDataJSON
        Map<String, Object> clientData = parseJsonMap(clientDataJson, "clientDataJSON");
        if (!"webauthn.create".equals(clientData.get("type"))) {
            throw new IllegalArgumentException("clientDataJSON.type is not webauthn.create");
        }
        byte[] clientChallenge;
        if (clientData.get("challenge") instanceof String challengeBase64Url) {
            clientChallenge = Base64.getUrlDecoder().decode(challengeBase64Url);
        } else {
            throw new IllegalArgumentException("clientDataJSON.challenge is missing");
        }
        if (!MessageDigest.isEqual(clientChallenge, expectedChallenge)) {
            throw new IllegalArgumentException("clientDataJSON.challenge does not match the issued challenge");
        }
        String origin = clientData.get("origin") instanceof String o ? o : null;
        if (origin == null || !origin.equals(expectedOrigin)) {
            throw new IllegalArgumentException("clientDataJSON.origin does not match the request origin");
        }

        // 2. attestationObject
        CBORObject attestation;
        try {
            attestation = CBORObject.DecodeFromBytes(attestationObject);
        } catch (CBORException e) {
            throw new IllegalArgumentException("attestationObject is not valid CBOR");
        }
        if (attestation.getType() != CBORType.Map) {
            throw new IllegalArgumentException("attestationObject is not a CBOR map");
        }
        // attestationObject is a CBOR map with TEXT keys (W3C WebAuthn L2, §6.2):
        // "fmt", "attStmt", "authData". Only the embedded COSE key (in authData)
        // uses integer labels.
        String format = mapTextItem(attestation, "fmt", "attestationObject", "fmt");
        CBORObject attStmt = mapItem(attestation, "attStmt", "attestationObject", "attStmt");
        if (attStmt.getType() != CBORType.Map) {
            throw new IllegalArgumentException("attestationObject.attStmt is not a map");
        }
        byte[] authData = mapByteStringItem(attestation, "authData", "attestationObject", "authData");

        // 3. authData
        if (authData.length < 37) {
            throw new IllegalArgumentException("authData is truncated");
        }
        byte[] rpIdHash = Arrays.copyOfRange(authData, 0, 32);
        byte flags = authData[32];
        long signCount = unsigned32(authData, 33);
        boolean userPresent = (flags & 0x01) != 0;
        boolean userVerified = (flags & 0x04) != 0;
        boolean hasAttestedCredential = (flags & 0x40) != 0;
        if (!userPresent) {
            throw new IllegalArgumentException("authenticator did not set the User Present flag");
        }
        if (!userVerified) {
            throw new IllegalArgumentException("authenticator did not set the User Verified flag");
        }
        if (!hasAttestedCredential) {
            throw new IllegalArgumentException("authData contains no attested credential data");
        }

        int offset = 37 + 16; // skip the AAGUID
        if (authData.length < offset + 2) {
            throw new IllegalArgumentException("attested credential data is truncated");
        }
        int credentialIdLength = unsigned16(authData, offset);
        offset += 2;
        if (credentialIdLength == 0 || authData.length < offset + credentialIdLength + 1) {
            throw new IllegalArgumentException("attested credential data is truncated");
        }
        byte[] attestedCredentialId = Arrays.copyOfRange(authData, offset, offset + credentialIdLength);
        offset += credentialIdLength;
        byte[] coseKeyBytes = Arrays.copyOfRange(authData, offset, authData.length);
        if (!MessageDigest.isEqual(attestedCredentialId, credentialId)) {
            throw new IllegalArgumentException("credentialId does not match the attested credential");
        }
        CBORObject coseKey;
        try {
            // Must consume exactly the remainder of authData (no trailing bytes).
            coseKey = CBORObject.DecodeFromBytes(coseKeyBytes);
        } catch (CBORException e) {
            throw new IllegalArgumentException("credential public key is not valid CBOR");
        }
        if (coseKey.getType() != CBORType.Map) {
            throw new IllegalArgumentException("credential public key is not a COSE key");
        }
        // Bound and validate the COSE key regardless of attestation format: the
        // raw bytes are persisted, so reject oversized or unparseable keys here
        // instead of trusting the attestation statement to have checked them.
        if (coseKeyBytes.length > MAX_PUBLIC_KEY_BYTES) {
            throw new IllegalArgumentException("credential public key exceeds the supported size");
        }
        toJavaPublicKey(coseKey);

        // 4. relying party hash
        if (!MessageDigest.isEqual(rpIdHash, sha256(rpId.getBytes(StandardCharsets.UTF_8)))) {
            throw new IllegalArgumentException("rpIdHash does not match the relying party id");
        }

        // 5. attestation statement (and, where present, the credential key signature)
        verifyAttestation(format, attStmt, coseKey, coseKeyBytes, attestedCredentialId,
            rpIdHash, authData, sha256(clientDataJson));

        return new Result(attestedCredentialId, base64UrlEncode(attestedCredentialId), coseKeyBytes, signCount);
    }

    private static void verifyAttestation(String format, CBORObject attStmt, CBORObject coseKey,
            byte[] coseKeyBytes, byte[] credentialId, byte[] rpIdHash, byte[] authData,
            byte[] clientDataHash) {
        // Signature base for the "none" and "packed" formats.
        byte[] signedData = concat(authData, clientDataHash);
        try {
            switch (format) {
                case "none" -> {
                    if (attStmt.size() != 0) {
                        throw new IllegalArgumentException("'none' attestation must have an empty attStmt");
                    }
                    // No signature to check: standard for platform authenticators,
                    // the key pair binding is proven at first use instead.
                }
                case "packed" -> {
                    byte[] signature = mapByteStringItem(attStmt, "sig", "attStmt", "sig");
                    Integer declaredAlg = declaredAttestationAlg(attStmt);
                    if (hasX5c(attStmt)) {
                        verifyWithCertificate(attestationCertificate(attStmt), signedData, signature,
                            declaredAlg);
                    } else {
                        // Self-attestation: signed with the credential key, so a
                        // declared algorithm must be the credential key's own.
                        if (declaredAlg != null && declaredAlg != mapIntItem(coseKey, 3, "COSE key", "alg")) {
                            throw new IllegalArgumentException(
                                "attStmt.alg does not match the credential key algorithm");
                        }
                        verifyWithKey(coseKey, signedData, signature, declaredAlg);
                    }
                }
                case "fido-u2f" -> {
                    // FIDO U2F signs a different base than packed/none:
                    // 0x00 || rpIdHash || clientDataHash || credentialId ||
                    // the uncompressed credential public key (FIDO U2F, §4.4).
                    byte[] upk = u2fUncompressedKey(coseKey);
                    byte[] u2fSignedData = new byte[1 + rpIdHash.length + clientDataHash.length
                        + credentialId.length + upk.length];
                    int offset = 0;
                    u2fSignedData[offset++] = 0x00;
                    System.arraycopy(rpIdHash, 0, u2fSignedData, offset, rpIdHash.length);
                    offset += rpIdHash.length;
                    System.arraycopy(clientDataHash, 0, u2fSignedData, offset, clientDataHash.length);
                    offset += clientDataHash.length;
                    System.arraycopy(credentialId, 0, u2fSignedData, offset, credentialId.length);
                    offset += credentialId.length;
                    System.arraycopy(upk, 0, u2fSignedData, offset, upk.length);

                    // WebAuthn L2 §8.6: this format requires x5c with exactly
                    // one certificate, and the signature is verified with the
                    // certificate's public key — unlike packed, there is no
                    // self-attestation path for fido-u2f.
                    CBORObject x5c = attStmt.ContainsKey("x5c") ? attStmt.get("x5c") : null;
                    if (x5c == null || x5c.getType() != CBORType.Array || x5c.size() != 1) {
                        throw new IllegalArgumentException(
                            "fido-u2f attestation requires exactly one x5c certificate");
                    }
                    PublicKey key = attestationCertificate(attStmt).getPublicKey();
                    if (!(key instanceof java.security.interfaces.ECPublicKey)
                            || !((java.security.interfaces.ECPublicKey) key).getParams().getCurve()
                                .equals(P256.getCurve())) {
                        throw new IllegalArgumentException(
                            "fido-u2f attestation certificate key must be a P-256 EC key");
                    }
                    verifyWithCertificateKey(key, u2fSignedData,
                        mapByteStringItem(attStmt, "sig", "attStmt", "sig"), null);
                }
                default -> throw new IllegalArgumentException("Unsupported attestation format: " + format);
            }
        } catch (CBORException | IllegalArgumentException e) {
            throw e;
        } catch (GeneralSecurityException e) {
            throw new IllegalArgumentException("Attestation verification failed: " + e.getMessage());
        }
    }

    /**
     * FIDO U2F uncompressed public key ({@code 0x04 || X || Y}). U2F is EC-only,
     * so a non-EC credential key is rejected for this attestation format, and
     * WebAuthn L2 §8.6 requires the coordinates to be exactly 32 bytes.
     */
    private static byte[] u2fUncompressedKey(CBORObject coseKey) {
        if (mapIntItem(coseKey, 1, "COSE key", "kty") != 2) {
            throw new IllegalArgumentException("fido-u2f attestation requires an EC credential key");
        }
        byte[] x = mapByteStringItem(coseKey, -2, "COSE key", "x");
        byte[] y = mapByteStringItem(coseKey, -3, "COSE key", "y");
        if (x.length != 32 || y.length != 32) {
            throw new IllegalArgumentException("fido-u2f credential key coordinates must be 32 bytes");
        }
        byte[] upk = new byte[1 + x.length + y.length];
        upk[0] = 0x04;
        System.arraycopy(x, 0, upk, 1, x.length);
        System.arraycopy(y, 0, upk, 1 + x.length, y.length);
        return upk;
    }

    private static boolean hasX5c(CBORObject attStmt) {
        if (!attStmt.ContainsKey("x5c")) {
            return false;
        }
        CBORObject x5c = attStmt.get("x5c");
        return x5c.getType() == CBORType.Array && x5c.size() > 0;
    }

    private static X509Certificate attestationCertificate(CBORObject attStmt) throws GeneralSecurityException {
        byte[] der = attStmt.get("x5c").get(0).GetByteString();
        return (X509Certificate) CertificateFactory.getInstance("X.509")
            .generateCertificate(new ByteArrayInputStream(der));
    }

    private static void verifyWithKey(CBORObject coseKey, byte[] signedData, byte[] signature,
            Integer declaredAlg) {
        try {
            PublicKey key = toJavaPublicKey(coseKey);
            Signature verifier = Signature.getInstance(signatureAlgorithm(declaredAlg, key));
            verifier.initVerify(key);
            verifier.update(signedData);
            if (!verifier.verify(signature)) {
                throw new IllegalArgumentException("Attestation signature verification failed");
            }
        } catch (IllegalArgumentException e) {
            throw e;
        } catch (GeneralSecurityException e) {
            throw new IllegalArgumentException("Attestation verification failed: " + e.getMessage());
        }
    }

    private static void verifyWithCertificate(X509Certificate certificate, byte[] signedData, byte[] signature,
            Integer declaredAlg) {
        verifyWithCertificateKey(certificate.getPublicKey(), signedData, signature, declaredAlg);
    }

    private static void verifyWithCertificateKey(PublicKey key, byte[] signedData, byte[] signature,
            Integer declaredAlg) {
        try {
            Signature verifier = Signature.getInstance(signatureAlgorithm(declaredAlg, key));
            verifier.initVerify(key);
            verifier.update(signedData);
            if (!verifier.verify(signature)) {
                throw new IllegalArgumentException("Attestation signature verification failed");
            }
        } catch (IllegalArgumentException e) {
            throw e;
        } catch (GeneralSecurityException e) {
            throw new IllegalArgumentException("Attestation verification failed: " + e.getMessage());
        }
    }

    /**
     * The algorithm a packed attestation statement declares for {@code sig},
     * or {@code null} when the statement carries none (it is optional). Only
     * the SHA-256 algorithms of the supported credential keys can be
     * verified, so anything else is rejected up front.
     */
    private static Integer declaredAttestationAlg(CBORObject attStmt) {
        if (!attStmt.ContainsKey("alg")) {
            return null;
        }
        int alg = mapIntItem(attStmt, "alg", "attStmt", "alg");
        if (alg != -7 && alg != -257) {
            throw new IllegalArgumentException("Unsupported attestation algorithm: " + alg);
        }
        return alg;
    }

    /**
     * Signature algorithm for an attestation signature: the declared
     * attStmt.alg when present, otherwise derived from the key type. A
     * declared algorithm that contradicts the key type (e.g. RS256 declared
     * but an EC key) fails in {@link Signature#initVerify} with an
     * {@link InvalidKeyException}.
     */
    private static String signatureAlgorithm(Integer declaredAlg, PublicKey key) {
        if (declaredAlg != null) {
            return declaredAlg == -7 ? "SHA256withECDSA" : "SHA256withRSA";
        }
        return key instanceof java.security.interfaces.RSAPublicKey ? "SHA256withRSA" : "SHA256withECDSA";
    }

    /** COSE key (CBOR) → JDK public key. ES256 (P-256) and RS256 are supported. */
    private static PublicKey toJavaPublicKey(CBORObject coseKey) {
        int kty = mapIntItem(coseKey, 1, "COSE key", "kty");
        int alg = mapIntItem(coseKey, 3, "COSE key", "alg");
        try {
            if (kty == 2) {
                if (alg != -7) {
                    throw new IllegalArgumentException("Unsupported COSE algorithm: " + alg);
                }
                if (mapIntItem(coseKey, -1, "COSE key", "crv") != 1) {
                    throw new IllegalArgumentException("Only the P-256 curve is supported");
                }
                BigInteger x = new BigInteger(1, mapByteStringItem(coseKey, -2, "COSE key", "x"));
                BigInteger y = new BigInteger(1, mapByteStringItem(coseKey, -3, "COSE key", "y"));
                return KeyFactory.getInstance("EC").generatePublic(new ECPublicKeySpec(new ECPoint(x, y), P256));
            }
            if (kty == 3) {
                if (alg != -257) {
                    throw new IllegalArgumentException("Unsupported COSE algorithm: " + alg);
                }
                BigInteger modulus = new BigInteger(1, mapByteStringItem(coseKey, -1, "COSE key", "n"));
                BigInteger exponent = new BigInteger(1, mapByteStringItem(coseKey, -2, "COSE key", "e"));
                return KeyFactory.getInstance("RSA").generatePublic(new RSAPublicKeySpec(modulus, exponent));
            }
            throw new IllegalArgumentException("Unsupported COSE key type: " + kty);
        } catch (IllegalArgumentException e) {
            throw e;
        } catch (GeneralSecurityException e) {
            throw new IllegalArgumentException("Credential public key is malformed: " + e.getMessage(), e);
        }
    }

    private static CBORObject mapItem(CBORObject map, int key, String what, String field) {
        if (!map.ContainsKey(key)) {
            throw new IllegalArgumentException(what + " is missing " + field);
        }
        return map.get(key);
    }

    private static String mapTextItem(CBORObject map, int key, String what, String field) {
        CBORObject item = mapItem(map, key, what, field);
        if (item.getType() != CBORType.TextString) {
            throw new IllegalArgumentException(what + "." + field + " is not a string");
        }
        return item.AsString();
    }

    private static int mapIntItem(CBORObject map, int key, String what, String field) {
        CBORObject item = mapItem(map, key, what, field);
        // cbor 4.x reports integers as CBORType.Integer (Number is the generic
        // numeric type), so accept both.
        if (item.getType() != CBORType.Integer && item.getType() != CBORType.Number) {
            throw new IllegalArgumentException(what + "." + field + " is not an integer");
        }
        return item.AsInt32Value();
    }

    private static byte[] mapByteStringItem(CBORObject map, int key, String what, String field) {
        CBORObject item = mapItem(map, key, what, field);
        if (item.getType() != CBORType.ByteString) {
            throw new IllegalArgumentException(what + "." + field + " is not a byte string");
        }
        return item.GetByteString();
    }

    /**
     * Text-key variants for {@code attestationObject} and the attestation
     * statement, which use text labels per W3C WebAuthn L2 §6.2 ("fmt",
     * "attStmt", "authData", "sig", "x5c", ...). The integer-key variants
     * above are for the COSE key (RFC 8152), which uses integer labels.
     */
    private static CBORObject mapItem(CBORObject map, String key, String what, String field) {
        if (!map.ContainsKey(key)) {
            throw new IllegalArgumentException(what + " is missing " + field);
        }
        return map.get(key);
    }

    private static String mapTextItem(CBORObject map, String key, String what, String field) {
        CBORObject item = mapItem(map, key, what, field);
        if (item.getType() != CBORType.TextString) {
            throw new IllegalArgumentException(what + "." + field + " is not a string");
        }
        return item.AsString();
    }

    private static int mapIntItem(CBORObject map, String key, String what, String field) {
        CBORObject item = mapItem(map, key, what, field);
        if (item.getType() != CBORType.Integer && item.getType() != CBORType.Number) {
            throw new IllegalArgumentException(what + "." + field + " is not an integer");
        }
        return item.AsInt32Value();
    }

    private static byte[] mapByteStringItem(CBORObject map, String key, String what, String field) {
        CBORObject item = mapItem(map, key, what, field);
        if (item.getType() != CBORType.ByteString) {
            throw new IllegalArgumentException(what + "." + field + " is not a byte string");
        }
        return item.GetByteString();
    }

    private static Map<String, Object> parseJsonMap(byte[] json, String what) {
        try {
            return OBJECT_MAPPER.readValue(json, MAP_TYPE);
        } catch (Exception e) {
            throw new IllegalArgumentException(what + " is not valid JSON");
        }
    }

    private static byte[] sha256(byte[] input) {
        try {
            return MessageDigest.getInstance("SHA-256").digest(input);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 unavailable", e);
        }
    }

    private static int unsigned16(byte[] data, int offset) {
        return ((data[offset] & 0xFF) << 8) | (data[offset + 1] & 0xFF);
    }

    private static long unsigned32(byte[] data, int offset) {
        return ((long) (data[offset] & 0xFF) << 24)
            | ((long) (data[offset + 1] & 0xFF) << 16)
            | ((long) (data[offset + 2] & 0xFF) << 8)
            | (data[offset + 3] & 0xFF);
    }

    private static byte[] concat(byte[] a, byte[] b) {
        byte[] result = new byte[a.length + b.length];
        System.arraycopy(a, 0, result, 0, a.length);
        System.arraycopy(b, 0, result, a.length, b.length);
        return result;
    }

    /** WebAuthn base64url: standard alphabet, URL-safe characters, no padding. */
    public static String base64UrlEncode(byte[] bytes) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    public static byte[] base64UrlDecode(String value) {
        if (value == null) {
            throw new IllegalArgumentException("Missing base64url value");
        }
        try {
            return Base64.getUrlDecoder().decode(value);
        } catch (IllegalArgumentException e) {
            throw new IllegalArgumentException("Value is not valid base64url", e);
        }
    }
}
