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
        return teamRepository.findByKeycloakGroup(roleName).orElseGet(() -> {
            String derivedName = KeycloakUserSyncService.deriveTeamName(roleName, teamRoleSuffixes);
            // Adopt an existing unlinked team with the same name rather than creating a duplicate.
            Optional<Team> byName = teamRepository.findFirstByName(derivedName)
                .filter(t -> t.getKeycloakGroup() == null);
            if (byName.isPresent()) {
                Team existing = byName.get();
                existing.setKeycloakGroup(roleName);
                return teamRepository.save(existing);
            }
            Team team = new Team();
            team.setKeycloakGroup(roleName);
            team.setName(derivedName);
            return teamRepository.save(team);
        });
    }
}
