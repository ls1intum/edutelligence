package de.tum.cit.aet.logos.logoswebservice.identity.sync;

import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakClaims;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.service.KeycloakUserSyncService;

@Component
@ConditionalOnProperty(prefix = "logos.auth.sync", name = "enabled", havingValue = "true")
public class KeycloakDirectorySyncJob implements KeycloakDirectorySync {

    private static final Logger log = LoggerFactory.getLogger(KeycloakDirectorySyncJob.class);

    private final KeycloakAdminClient adminClient;
    private final KeycloakUserSyncService syncService;
    private final UserRepository userRepository;

    public KeycloakDirectorySyncJob(KeycloakAdminClient adminClient, KeycloakUserSyncService syncService,
                                    UserRepository userRepository) {
        this.adminClient = adminClient;
        this.syncService = syncService;
        this.userRepository = userRepository;
    }

    @Override
    @Scheduled(cron = "${logos.auth.sync.cron:0 0 0 * * *}")
    public void syncAll() {
        Map<String, Map<String, Object>> keycloakUsers;
        try {
            keycloakUsers = adminClient.listUsersById();
        } catch (Exception e) {
            log.warn("Keycloak directory sync aborted: could not fetch user list: {}", e.getMessage());
            return;
        }

        for (User user : userRepository.findByKeycloakIdIsNotNull()) {
            String keycloakId = user.getKeycloakId().toString();
            try {
                Map<String, Object> rep = keycloakUsers.get(keycloakId);
                if (rep == null || Boolean.FALSE.equals(rep.get("enabled"))) {
                    syncService.deactivateUser(user);
                    continue;
                }
                syncService.syncFromClaims(new KeycloakClaims(
                    keycloakId,
                    null,
                    rep.get("firstName") instanceof String s ? s : "",
                    rep.get("lastName") instanceof String s ? s : "",
                    rep.get("email") instanceof String s ? s : null,
                    adminClient.getUserClaimNames(keycloakId),
                    null));
            } catch (Exception e) {
                log.warn("Keycloak directory sync failed for user {}: {}", user.getId(), e.getMessage());
            }
        }
        log.info("Keycloak directory sync completed");
    }
}
