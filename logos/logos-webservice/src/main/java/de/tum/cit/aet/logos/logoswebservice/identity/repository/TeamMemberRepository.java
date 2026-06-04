package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMember;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMemberId;

public interface TeamMemberRepository extends JpaRepository<TeamMember, TeamMemberId> {

    List<TeamMember> findById_TeamId(Integer teamId);

    @Query("SELECT COUNT(tm) > 0 FROM TeamMember tm WHERE tm.id.teamId = :teamId AND tm.id.userId = :userId")
    boolean isMember(@Param("teamId") Integer teamId, @Param("userId") Integer userId);

    @Query("SELECT COUNT(tm) > 0 FROM TeamMember tm WHERE tm.id.teamId = :teamId AND tm.id.userId = :userId AND tm.isOwner = true")
    boolean isOwner(@Param("teamId") Integer teamId, @Param("userId") Integer userId);
}