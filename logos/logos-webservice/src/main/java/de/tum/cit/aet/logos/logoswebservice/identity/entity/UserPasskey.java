package de.tum.cit.aet.logos.logoswebservice.identity.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * A WebAuthn credential (passkey) registered by a user (#694). The credential
 * id is stored base64url-encoded as returned by the browser; the public key
 * holds the raw COSE key bytes from the registration attestation.
 */
@Entity
@Table(name = "user_passkeys")
public class UserPasskey {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Integer userId;

    @Column(nullable = false)
    private String credentialId;

    @Column(nullable = false)
    private byte[] publicKey;

    @Column(nullable = false)
    private Long signCount = 0L;

    private String label;

    @Column(nullable = false)
    private Instant createdAt;

    public Long getId() { return id; }
    public Integer getUserId() { return userId; }
    public String getCredentialId() { return credentialId; }
    public byte[] getPublicKey() { return publicKey; }
    public Long getSignCount() { return signCount; }
    public String getLabel() { return label; }
    public Instant getCreatedAt() { return createdAt; }

    public void setUserId(Integer userId) { this.userId = userId; }
    public void setCredentialId(String credentialId) { this.credentialId = credentialId; }
    public void setPublicKey(byte[] publicKey) { this.publicKey = publicKey; }
    public void setSignCount(Long signCount) { this.signCount = signCount; }
    public void setLabel(String label) { this.label = label; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }
}
