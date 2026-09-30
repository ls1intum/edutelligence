package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamRepoLink;

public interface TeamRepoLinkRepository extends JpaRepository<TeamRepoLink, Integer> {

    List<TeamRepoLink> findByTeamIdOrderByRepoSlugAsc(Integer teamId);

    Optional<TeamRepoLink> findByIdAndTeamId(Integer id, Integer teamId);

    boolean existsByTeamIdAndRepoSlug(Integer teamId, String repoSlug);

    boolean existsByTeamIdAndRepoSlugAndIdNot(Integer teamId, String repoSlug, Integer id);
}
