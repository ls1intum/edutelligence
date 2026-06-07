package de.tum.cit.aet.logos.logoswebservice.identity.entity;

import jakarta.persistence.Column;
import jakarta.persistence.EmbeddedId;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;

@Entity
@Table(name = "team_members")
public class TeamMember {

    @EmbeddedId
    private TeamMemberId id;

    @Column(name = "is_owner", nullable = false)
    private Boolean isOwner = false;

    public TeamMemberId getId() { return id; }
    public Boolean getIsOwner() { return isOwner; }
    public void setId(TeamMemberId id) { this.id = id; }
    public void setIsOwner(Boolean isOwner) { this.isOwner = isOwner; }
}
