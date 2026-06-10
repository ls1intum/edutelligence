package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

import java.io.Serializable;
import java.util.Objects;
import jakarta.persistence.Embeddable;

@Embeddable
public class TeamModelPermissionId implements Serializable {
    private Integer teamId;
    private Integer modelId;

    public TeamModelPermissionId() {}
    public TeamModelPermissionId(Integer teamId, Integer modelId) {
        this.teamId = teamId;
        this.modelId = modelId;
    }

    public Integer getTeamId() { return teamId; }
    public Integer getModelId() { return modelId; }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof TeamModelPermissionId that)) return false;
        return Objects.equals(teamId, that.teamId) && Objects.equals(modelId, that.modelId);
    }
    @Override public int hashCode() { return Objects.hash(teamId, modelId); }
}
