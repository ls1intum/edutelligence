package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

import jakarta.persistence.EmbeddedId;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;

@Entity
@Table(name = "team_provider_permissions")
public class TeamProviderPermission {
    @EmbeddedId
    private TeamProviderPermissionId id;

    public TeamProviderPermission() {}
    public TeamProviderPermission(Integer teamId, Integer providerId) {
        this.id = new TeamProviderPermissionId(teamId, providerId);
    }

    public TeamProviderPermissionId getId() { return id; }
    public void setId(TeamProviderPermissionId id) { this.id = id; }
}
