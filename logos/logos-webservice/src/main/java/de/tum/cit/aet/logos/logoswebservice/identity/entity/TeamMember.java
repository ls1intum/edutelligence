package de.tum.cit.aet.logos.logoswebservice.identity.entity;

import jakarta.persistence.Column;
import jakarta.persistence.EmbeddedId;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Table;

@Entity
@Table(name = "team_members")
public class TeamMember {

    @EmbeddedId
    private TeamMemberId id;

    @Column(nullable = false)
    private Boolean isOwner = false;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private TeamMemberSource source = TeamMemberSource.MANUAL;

    public TeamMemberId getId() { return id; }
    public Boolean getIsOwner() { return isOwner; }
    public TeamMemberSource getSource() { return source; }
    public void setId(TeamMemberId id) { this.id = id; }
    public void setIsOwner(Boolean isOwner) { this.isOwner = isOwner; }
    public void setSource(TeamMemberSource source) { this.source = source; }
}
