package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.util.List;

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
        return teamRepository.findByKeycloakGroup(roleName).orElseGet(() -> {
            Team team = new Team();
            team.setKeycloakGroup(roleName);
            team.setName(KeycloakUserSyncService.deriveTeamName(roleName, teamRoleSuffixes));
            return teamRepository.save(team);
        });
    }
}
