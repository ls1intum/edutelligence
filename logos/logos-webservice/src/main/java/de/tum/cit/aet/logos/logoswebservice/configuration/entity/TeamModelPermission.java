package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

import jakarta.persistence.EmbeddedId;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;

@Entity
@Table(name = "team_model_permissions")
public class TeamModelPermission {
    @EmbeddedId
    private TeamModelPermissionId id;

    public TeamModelPermission() {}
    public TeamModelPermission(Integer teamId, Integer modelId) {
        this.id = new TeamModelPermissionId(teamId, modelId);
    }

    public TeamModelPermissionId getId() { return id; }
    public void setId(TeamModelPermissionId id) { this.id = id; }
}
