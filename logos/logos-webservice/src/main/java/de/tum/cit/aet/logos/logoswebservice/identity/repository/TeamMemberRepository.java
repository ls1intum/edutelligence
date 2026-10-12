package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMember;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMemberId;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMemberSource;
import jakarta.persistence.LockModeType;

public interface TeamMemberRepository extends JpaRepository<TeamMember, TeamMemberId> {

    List<TeamMember> findById_TeamId(Integer teamId);

    /**
     * Locks the membership row until the surrounding transaction ends. Leaving
     * a team acquires it before sweeping the team's keys, and minting session
     * keys acquires it before re-checking the owner, so the two serialize and
     * cannot commit around each other.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT tm FROM TeamMember tm WHERE tm.id.userId = :userId AND tm.id.teamId = :teamId")
    Optional<TeamMember> findByIdForUpdate(@Param("userId") Integer userId, @Param("teamId") Integer teamId);

    /** Members of a team whose underlying user account is still active. */
    @Query("""
        SELECT tm FROM TeamMember tm
        JOIN User u ON u.id = tm.id.userId
        WHERE tm.id.teamId = :teamId AND u.isActive = true
        """)
    List<TeamMember> findActiveById_TeamId(@Param("teamId") Integer teamId);

    List<TeamMember> findById_UserId(Integer userId);

    @Query("SELECT COUNT(tm) > 0 FROM TeamMember tm WHERE tm.id.teamId = :teamId AND tm.id.userId = :userId")
    boolean isMember(@Param("teamId") Integer teamId, @Param("userId") Integer userId);

    @Query("SELECT COUNT(tm) > 0 FROM TeamMember tm WHERE tm.id.teamId = :teamId AND tm.id.userId = :userId AND tm.isOwner = true")
    boolean isOwner(@Param("teamId") Integer teamId, @Param("userId") Integer userId);

    List<TeamMember> findById_UserIdAndSource(Integer userId, TeamMemberSource source);

    List<TeamMember> findById_TeamIdAndSource(Integer teamId, TeamMemberSource source);

    boolean existsById_UserIdAndIsOwnerTrue(Integer userId);
}
