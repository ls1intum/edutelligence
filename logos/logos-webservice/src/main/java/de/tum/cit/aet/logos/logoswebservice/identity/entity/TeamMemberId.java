package de.tum.cit.aet.logos.logoswebservice.identity.entity;

import java.io.Serializable;
import java.util.Objects;

import jakarta.persistence.Column;
import jakarta.persistence.Embeddable;

@Embeddable
public class TeamMemberId implements Serializable {

    @Column(name = "user_id")
    private Integer userId;

    @Column(name = "team_id")
    private Integer teamId;

    public TeamMemberId() {}

    public TeamMemberId(Integer userId, Integer teamId) {
        this.userId = userId;
        this.teamId = teamId;
    }

    public Integer getUserId() { return userId; }
    public Integer getTeamId() { return teamId; }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof TeamMemberId)) return false;
        TeamMemberId that = (TeamMemberId) o;
        return Objects.equals(userId, that.userId) && Objects.equals(teamId, that.teamId);
    }

    @Override
    public int hashCode() { return Objects.hash(userId, teamId); }
}
