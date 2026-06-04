package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.Team;

public interface TeamRepository extends JpaRepository<Team, Integer> {

    @Query("""
        SELECT DISTINCT t FROM Team t
        JOIN TeamMember tm ON tm.id.teamId = t.id
        WHERE tm.id.userId = :userId
        """)
    List<Team> findTeamsForUser(@Param("userId") Integer userId);
}