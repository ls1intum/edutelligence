package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.Base64;
import java.util.concurrent.atomic.AtomicBoolean;

import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * AES-GCM helpers for deploy-key PEMs stored in {@code team_repository_credentials}.
 *
 * <p>Key material comes from {@code LOGOS_REPO_CREDENTIALS_KEY} (URL-safe or
 * standard Base64 of exactly 32 bytes). When unset, a documented development
 * default string is hashed with SHA-256 and a one-time warning is logged.
 */
@Component
public class RepoCredentialCrypto {

    private static final Logger log = LoggerFactory.getLogger(RepoCredentialCrypto.class);

    /** Documented development fallback — never use in production. */
    static final String DEV_DEFAULT_PASSPHRASE =
        "logos-dev-repo-credentials-key-do-not-use-in-prod";

    private static final String ENV_KEY = "LOGOS_REPO_CREDENTIALS_KEY";
    private static final int KEY_BYTES = 32;
    private static final int IV_BYTES = 12;
    private static final int TAG_BITS = 128;

    private final SecretKey secretKey;
    private static final AtomicBoolean DEV_WARNED = new AtomicBoolean(false);

    public RepoCredentialCrypto() {
        this(resolveKey());
    }

    RepoCredentialCrypto(SecretKey secretKey) {
        this.secretKey = secretKey;
    }

    public String encrypt(String plaintext) {
        if (plaintext == null) {
            throw new IllegalArgumentException("plaintext must not be null");
        }
        try {
            byte[] iv = new byte[IV_BYTES];
            new SecureRandom().nextBytes(iv);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, secretKey, new GCMParameterSpec(TAG_BITS, iv));
            byte[] ciphertext = cipher.doFinal(plaintext.getBytes(StandardCharsets.UTF_8));
            ByteBuffer buf = ByteBuffer.allocate(iv.length + ciphertext.length);
            buf.put(iv);
            buf.put(ciphertext);
            return Base64.getEncoder().encodeToString(buf.array());
        }
        catch (Exception e) {
            throw new IllegalStateException("Failed to encrypt repository credential", e);
        }
    }

    public String decrypt(String encoded) {
        if (encoded == null || encoded.isBlank()) {
            throw new IllegalArgumentException("ciphertext must not be blank");
        }
        try {
            byte[] all = Base64.getDecoder().decode(encoded);
            if (all.length <= IV_BYTES) {
                throw new IllegalArgumentException("ciphertext too short");
            }
            byte[] iv = Arrays.copyOfRange(all, 0, IV_BYTES);
            byte[] ciphertext = Arrays.copyOfRange(all, IV_BYTES, all.length);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, secretKey, new GCMParameterSpec(TAG_BITS, iv));
            return new String(cipher.doFinal(ciphertext), StandardCharsets.UTF_8);
        }
        catch (IllegalArgumentException e) {
            throw e;
        }
        catch (Exception e) {
            throw new IllegalStateException("Failed to decrypt repository credential", e);
        }
    }

    /** SHA-256 hex fingerprint of the stored PEM (or any string payload). */
    public static String fingerprint(String pem) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest(pem.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder(hash.length * 2);
            for (byte b : hash) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        }
        catch (Exception e) {
            throw new IllegalStateException("Failed to fingerprint credential", e);
        }
    }

    private static SecretKey resolveKey() {
        String env = System.getenv(ENV_KEY);
        if (env != null && !env.isBlank()) {
            byte[] raw;
            try {
                raw = Base64.getDecoder().decode(env.trim());
            }
            catch (IllegalArgumentException e) {
                raw = Base64.getUrlDecoder().decode(env.trim());
            }
            if (raw.length != KEY_BYTES) {
                throw new IllegalStateException(
                    ENV_KEY + " must decode to exactly " + KEY_BYTES + " bytes, got " + raw.length);
            }
            return new SecretKeySpec(raw, "AES");
        }
        if (DEV_WARNED.compareAndSet(false, true)) {
            log.warn(
                "{} is unset; deriving AES key from the documented development default. "
                    + "Set {} (Base64 of 32 random bytes) before storing real deploy keys.",
                ENV_KEY, ENV_KEY);
        }
        try {
            byte[] raw = MessageDigest.getInstance("SHA-256")
                .digest(DEV_DEFAULT_PASSPHRASE.getBytes(StandardCharsets.UTF_8));
            return new SecretKeySpec(raw, "AES");
        }
        catch (Exception e) {
            throw new IllegalStateException("Failed to derive development credential key", e);
        }
    }
}
