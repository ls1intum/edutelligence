package de.tum.cit.aet.logos.logoswebservice.identity.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.Base64;

import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;

import org.junit.jupiter.api.Test;

class RepoCredentialCryptoTest {

    @Test
    void encryptDecrypt_roundTrips() {
        byte[] keyBytes = new byte[32];
        for (int i = 0; i < keyBytes.length; i++) {
            keyBytes[i] = (byte) i;
        }
        SecretKey key = new SecretKeySpec(keyBytes, "AES");
        RepoCredentialCrypto crypto = new RepoCredentialCrypto(key);

        String pem = "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----\n";
        String encrypted = crypto.encrypt(pem);
        assertThat(encrypted).isNotEqualTo(pem);
        assertThat(Base64.getDecoder().decode(encrypted).length).isGreaterThan(12);
        assertThat(crypto.decrypt(encrypted)).isEqualTo(pem);
        assertThat(RepoCredentialCrypto.fingerprint(pem)).hasSize(64);
    }

    @Test
    void withoutKey_reportsUnconfiguredAndRefusesCrypto() {
        RepoCredentialCrypto crypto = new RepoCredentialCrypto(null);

        assertThat(crypto.isConfigured()).isFalse();
        assertThatThrownBy(() -> crypto.encrypt("pem"))
            .isInstanceOf(IllegalStateException.class)
            .hasMessageContaining("LOGOS_REPO_CREDENTIALS_KEY");
        assertThatThrownBy(() -> crypto.decrypt("Y2lwaGVydGV4dC1wbGFjZWhvbGRlcg=="))
            .isInstanceOf(IllegalStateException.class);
    }
}
