package de.tum.cit.aet.logos.logoswebservice.identity.entity;

import java.time.Instant;
import java.util.UUID;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "users")
public class User {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(nullable = false)
    private String username;

    @Column(nullable = false)
    private String prename;

    @Column(nullable = false)
    private String name;

    @Column(nullable = false)
    private String role;

    private String email;

    @Column(unique = true)
    private UUID keycloakId;

    private Instant lastSyncedAt;

    @Column(nullable = false)
    private Boolean isActive = true;

    public Integer getId() { return id; }
    public String getUsername() { return username; }
    public String getPrename() { return prename; }
    public String getName() { return name; }
    public String getRole() { return role; }
    public String getEmail() { return email; }
    public UUID getKeycloakId() { return keycloakId; }
    public Instant getLastSyncedAt() { return lastSyncedAt; }
    public Boolean getIsActive() { return isActive; }
    public void setUsername(String username) { this.username = username; }
    public void setPrename(String prename) { this.prename = prename; }
    public void setName(String name) { this.name = name; }
    public void setRole(String role) { this.role = role; }
    public void setEmail(String email) { this.email = email; }
    public void setKeycloakId(UUID keycloakId) { this.keycloakId = keycloakId; }
    public void setLastSyncedAt(Instant lastSyncedAt) { this.lastSyncedAt = lastSyncedAt; }
    public void setIsActive(Boolean isActive) { this.isActive = isActive; }
}
