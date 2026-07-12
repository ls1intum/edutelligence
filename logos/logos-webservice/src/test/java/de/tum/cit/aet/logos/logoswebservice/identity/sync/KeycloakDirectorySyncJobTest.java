package de.tum.cit.aet.logos.logoswebservice.identity.sync;

import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakClaims;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.service.KeycloakUserSyncService;

class KeycloakDirectorySyncJobTest {

    private final KeycloakAdminClient adminClient = mock(KeycloakAdminClient.class);
    private final KeycloakUserSyncService syncService = mock(KeycloakUserSyncService.class);
    private final UserRepository userRepository = mock(UserRepository.class);
    private final KeycloakDirectorySyncJob job =
        new KeycloakDirectorySyncJob(adminClient, syncService, userRepository);

    @Test
    void syncAll_syncsClaims_forActiveUser() {
        UUID kcId = UUID.fromString("aaaaaaaa-0000-0000-0000-000000000001");
        User user = userWithKeycloakId(kcId);
        when(userRepository.findByKeycloakIdIsNotNull()).thenReturn(List.of(user));
        when(adminClient.listUsersById()).thenReturn(Map.of(kcId.toString(),
            Map.of("username", "alice", "firstName", "Alice", "lastName", "Smith",
                   "email", "alice@example.com", "enabled", true)));
        when(adminClient.getUserClaimNames(kcId.toString())).thenReturn(Set.of("app_developer"));

        job.syncAll();

        ArgumentCaptor<KeycloakClaims> cap = ArgumentCaptor.forClass(KeycloakClaims.class);
        verify(syncService).syncFromClaims(cap.capture());
        KeycloakClaims claims = cap.getValue();
        assertThat(claims.keycloakId()).isEqualTo(kcId.toString());
        assertThat(claims.username()).isNull();
        assertThat(claims.roleNames()).containsExactly("app_developer");
    }

    @Test
    void syncAll_deactivatesUser_whenDisabledInKeycloak() {
        UUID kcId = UUID.fromString("aaaaaaaa-0000-0000-0000-000000000002");
        User user = userWithKeycloakId(kcId);
        when(userRepository.findByKeycloakIdIsNotNull()).thenReturn(List.of(user));
        when(adminClient.listUsersById()).thenReturn(Map.of(kcId.toString(),
            Map.of("username", "bob", "enabled", false)));

        job.syncAll();

        verify(syncService).deactivateUser(user);
        verify(syncService, never()).syncFromClaims(any(KeycloakClaims.class));
    }

    @Test
    void syncAll_deactivatesUser_whenNotFoundInKeycloak() {
        UUID kcId = UUID.fromString("aaaaaaaa-0000-0000-0000-000000000003");
        User user = userWithKeycloakId(kcId);
        when(userRepository.findByKeycloakIdIsNotNull()).thenReturn(List.of(user));
        when(adminClient.listUsersById()).thenReturn(Map.of());

        job.syncAll();

        verify(syncService).deactivateUser(user);
        verify(syncService, never()).syncFromClaims(any(KeycloakClaims.class));
    }

    @Test
    void syncAll_skipsUser_onAdminApiError() {
        UUID kcId = UUID.fromString("aaaaaaaa-0000-0000-0000-000000000004");
        User user = userWithKeycloakId(kcId);
        when(userRepository.findByKeycloakIdIsNotNull()).thenReturn(List.of(user));
        when(adminClient.listUsersById()).thenThrow(new RuntimeException("network error"));

        job.syncAll();

        verify(syncService, never()).deactivateUser(user);
        verify(syncService, never()).syncFromClaims(any(KeycloakClaims.class));
    }

    private static User userWithKeycloakId(UUID kcId) {
        User u = new User();
        u.setKeycloakId(kcId);
        u.setUsername("someuser");
        return u;
    }
}
