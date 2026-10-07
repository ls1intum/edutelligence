package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.util.List;
import java.util.Optional;

import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.Team;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;

@Component
class KeycloakTeamAutoProvisioner {

    private final TeamRepository teamRepository;

    KeycloakTeamAutoProvisioner(TeamRepository teamRepository) {
        this.teamRepository = teamRepository;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public Team findOrCreate(String roleName, List<String> teamRoleSuffixes) {
        Optional<Team> linked = teamRepository.findByKeycloakGroup(roleName);
        if (linked.isPresent()) return linked.get();

        String derivedName = KeycloakUserSyncService.deriveTeamName(roleName, teamRoleSuffixes);
        // Adopt an existing unlinked team with the same name rather than creating
        // a duplicate — but claim it with a conditional update, so a link an
        // admin commits in between wins instead of being silently replaced.
        Optional<Integer> adopted = teamRepository.findFirstByName(derivedName)
            .map(Team::getId)
            .filter(id -> teamRepository.adoptIfUnlinked(id, roleName) == 1);
        if (adopted.isPresent()) return teamRepository.findById(adopted.get()).orElseThrow();

        // The same-named team was taken; this group may meanwhile have a team of
        // its own, and otherwise gets a fresh one.
        return teamRepository.findByKeycloakGroup(roleName).orElseGet(() -> {
            Team team = new Team();
            team.setKeycloakGroup(roleName);
            team.setName(derivedName);
            return teamRepository.save(team);
        });
    }
}
