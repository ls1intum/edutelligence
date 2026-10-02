package de.tum.cit.aet.logos.logoswebservice.identity.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "team_repository_credentials")
public class TeamRepositoryCredential {

    @Id
    private Integer teamRepositoryId;

    @Column(nullable = false)
    private String accessType = "deploy_key";

    private String encryptedPrivateKey;
    private String publicKeyFingerprint;
    private Long githubAppInstallationId;

    @Column(nullable = false)
    private Instant createdAt;

    private Instant revokedAt;

    public Integer getTeamRepositoryId() { return teamRepositoryId; }
    public String getAccessType() { return accessType; }
    public String getEncryptedPrivateKey() { return encryptedPrivateKey; }
    public String getPublicKeyFingerprint() { return publicKeyFingerprint; }
    public Long getGithubAppInstallationId() { return githubAppInstallationId; }
    public Instant getCreatedAt() { return createdAt; }
    public Instant getRevokedAt() { return revokedAt; }

    public void setTeamRepositoryId(Integer teamRepositoryId) { this.teamRepositoryId = teamRepositoryId; }
    public void setAccessType(String accessType) { this.accessType = accessType; }
    public void setEncryptedPrivateKey(String encryptedPrivateKey) { this.encryptedPrivateKey = encryptedPrivateKey; }
    public void setPublicKeyFingerprint(String publicKeyFingerprint) { this.publicKeyFingerprint = publicKeyFingerprint; }
    public void setGithubAppInstallationId(Long githubAppInstallationId) { this.githubAppInstallationId = githubAppInstallationId; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }
    public void setRevokedAt(Instant revokedAt) { this.revokedAt = revokedAt; }

    public boolean isActive() {
        return revokedAt == null && encryptedPrivateKey != null && !encryptedPrivateKey.isBlank();
    }
}
