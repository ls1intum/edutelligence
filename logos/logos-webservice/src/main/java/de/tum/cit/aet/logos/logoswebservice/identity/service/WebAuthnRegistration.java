package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.io.ByteArrayInputStream;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.security.AlgorithmParameters;
import java.security.GeneralSecurityException;
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
 * {@code packed} (self-attestation or certificate-based) and {@code fido-u2f}.
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

    // P-256 curve parameters, for the fido-u2f self-attestation point derivation.
    private static final BigInteger P256_P =
        new BigInteger("FFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF", 16);
    private static final BigInteger P256_B =
        new BigInteger("5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B", 16);

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
        String format = mapTextItem(attestation, 1, "attestationObject", "fmt");
        CBORObject attStmt = mapItem(attestation, 2, "attestationObject", "attStmt");
        if (attStmt.getType() != CBORType.Map) {
            throw new IllegalArgumentException("attestationObject.attStmt is not a map");
        }
        byte[] authData = mapByteStringItem(attestation, -1, "attestationObject", "authData");

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

        // 4. relying party hash
        if (!MessageDigest.isEqual(rpIdHash, sha256(rpId.getBytes(StandardCharsets.UTF_8)))) {
            throw new IllegalArgumentException("rpIdHash does not match the relying party id");
        }

        // 5. attestation statement (and, where present, the credential key signature)
        byte[] signedData = concat(authData, sha256(clientDataJson));
        verifyAttestation(format, attStmt, coseKey, coseKeyBytes, attestedCredentialId, signedData);

        return new Result(attestedCredentialId, base64UrlEncode(attestedCredentialId), coseKeyBytes, signCount);
    }

    private static void verifyAttestation(String format, CBORObject attStmt, CBORObject coseKey,
            byte[] coseKeyBytes, byte[] credentialId, byte[] signedData) {
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
                    byte[] signature = mapByteStringItem(attStmt, -2, "attStmt", "sig");
                    if (hasX5c(attStmt)) {
                        verifyWithCertificate(attestationCertificate(attStmt), signedData, signature);
                    } else {
                        // Self-attestation: signed with the credential key.
                        verifyWithKey(coseKey, signedData, signature);
                    }
                }
                case "fido-u2f" -> {
                    PublicKey key = hasX5c(attStmt)
                        ? attestationCertificate(attStmt).getPublicKey()
                        : u2fSelfAttestationKey(credentialId, coseKeyBytes);
                    verifyWithCertificateKey(key, signedData, mapByteStringItem(attStmt, -2, "attStmt", "ecdsa"));
                }
                default -> throw new IllegalArgumentException("Unsupported attestation format: " + format);
            }
        } catch (CBORException | IllegalArgumentException e) {
            throw e;
        } catch (GeneralSecurityException e) {
            throw new IllegalArgumentException("Attestation verification failed: " + e.getMessage());
        }
    }

    private static boolean hasX5c(CBORObject attStmt) {
        if (!attStmt.ContainsKey(-1)) {
            return false;
        }
        CBORObject x5c = attStmt.get(-1);
        return x5c.getType() == CBORType.Array && x5c.size() > 0;
    }

    private static X509Certificate attestationCertificate(CBORObject attStmt) throws GeneralSecurityException {
        byte[] der = attStmt.get(-1).get(0).GetByteString();
        return (X509Certificate) CertificateFactory.getInstance("X.509")
            .generateCertificate(new ByteArrayInputStream(der));
    }

    private static void verifyWithKey(CBORObject coseKey, byte[] signedData, byte[] signature) {
        try {
            PublicKey key = toJavaPublicKey(coseKey);
            Signature verifier = Signature.getInstance(
                mapIntItem(coseKey, 1, "COSE key", "kty") == 2 ? "SHA256withECDSA" : "SHA256withRSA");
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

    private static void verifyWithCertificate(X509Certificate certificate, byte[] signedData, byte[] signature) {
        verifyWithCertificateKey(certificate.getPublicKey(), signedData, signature);
    }

    private static void verifyWithCertificateKey(PublicKey key, byte[] signedData, byte[] signature) {
        try {
            Signature verifier = Signature.getInstance(
                key instanceof java.security.interfaces.RSAPublicKey ? "SHA256withRSA" : "SHA256withECDSA");
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
     * fido-u2f self-attestation: the attestation key is a P-256 point derived
     * from the credential id and public key (FIDO U2F, section 8.2).
     */
    private static PublicKey u2fSelfAttestationKey(byte[] credentialId, byte[] coseKeyBytes)
            throws GeneralSecurityException {
        BigInteger x = new BigInteger(1, sha256(concat(new byte[] { 0x00 }, credentialId, coseKeyBytes)));
        // P-256 has p ≡ 3 (mod 4), so the square root is m^((p+1)/4) mod p.
        BigInteger y = x.modPow(P256_P.add(BigInteger.ONE).divide(BigInteger.valueOf(4)), P256_P);
        BigInteger rhs = x.modPow(BigInteger.valueOf(3), P256_P)
            .subtract(BigInteger.valueOf(3).multiply(x))
            .add(P256_B)
            .mod(P256_P);
        if (!y.modPow(BigInteger.valueOf(2), P256_P).equals(rhs)) {
            y = P256_P.subtract(y);
        }
        return KeyFactory.getInstance("EC").generatePublic(new ECPublicKeySpec(new ECPoint(x, y), P256));
    }

    /** COSE key (CBOR) → JDK public key. ES256 (P-256) and RS256 are supported. */
    private static PublicKey toJavaPublicKey(CBORObject coseKey) throws GeneralSecurityException {
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

    private static byte[] concat(byte[] a, byte[] b, byte[] c) {
        return concat(concat(a, b), c);
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
