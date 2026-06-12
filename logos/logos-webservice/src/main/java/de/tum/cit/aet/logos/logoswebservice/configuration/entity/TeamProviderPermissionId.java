package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

import java.io.Serializable;
import java.util.Objects;
import jakarta.persistence.Embeddable;

@Embeddable
public class TeamProviderPermissionId implements Serializable {
    private Integer teamId;
    private Integer providerId;

    public TeamProviderPermissionId() {}
    public TeamProviderPermissionId(Integer teamId, Integer providerId) {
        this.teamId = teamId;
        this.providerId = providerId;
    }

    public Integer getTeamId() { return teamId; }
    public Integer getProviderId() { return providerId; }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof TeamProviderPermissionId that)) return false;
        return Objects.equals(teamId, that.teamId) && Objects.equals(providerId, that.providerId);
    }
    @Override public int hashCode() { return Objects.hash(teamId, providerId); }
}
