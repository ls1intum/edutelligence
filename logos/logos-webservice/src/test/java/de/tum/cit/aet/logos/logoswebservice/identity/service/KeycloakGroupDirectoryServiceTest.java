package de.tum.cit.aet.logos.logoswebservice.identity.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.util.List;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;

import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakProperties;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.KeycloakGroupOptionDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.sync.KeycloakAdminClient;

class KeycloakGroupDirectoryServiceTest {

    private KeycloakAdminClient client;
    private TeamRepository teamRepository;
    private KeycloakGroupDirectoryService service;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        client = mock(KeycloakAdminClient.class);
        teamRepository = mock(TeamRepository.class);
        when(teamRepository.findByKeycloakGroupIsNotNull()).thenReturn(List.of());

        ObjectProvider<KeycloakAdminClient> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(client);

        KeycloakProperties props = new KeycloakProperties(
            "logos",
            new KeycloakProperties.Roles(List.of("itg-admin"), List.of("chair-member")),
            5, null, null, null, false);
        service = new KeycloakGroupDirectoryService(
            provider, new KeycloakGroupLinkNormalizer(props), teamRepository);
    }

    private List<String> names() {
        return service.list().groups().stream().map(KeycloakGroupOptionDTO::name).toList();
    }

    @Test
    void offersGroupsAndRolesWithoutTheReservedAdminRoles() {
        when(client.listGroupPaths()).thenReturn(List.of("parent/ios-26ws", "chair-member"));
        when(client.listRealmRoleNames()).thenReturn(
            List.of("maiss-dev", "itg-admin", "offline_access", "default-roles-tum"));

        assertThat(names()).containsExactly("maiss-dev", "parent/ios-26ws");
        assertThat(service.list().available()).isTrue();
    }

    // A service account may hold query-groups without view-realm, so one
    // listing failing must not discard the other.
    @Test
    void stillOffersTheListingThatCouldBeRead() {
        when(client.listGroupPaths()).thenThrow(new IllegalStateException("403"));
        when(client.listRealmRoleNames()).thenReturn(List.of("maiss-dev"));

        assertThat(service.list().available()).isTrue();
        assertThat(names()).containsExactly("maiss-dev");
    }

    // Caching half a directory would hide the other half for the whole TTL, so
    // a partial read must be served but not kept.
    @Test
    void doesNotCacheAPartialDirectory() {
        doThrow(new IllegalStateException("503")).when(client).listGroupPaths();
        when(client.listRealmRoleNames()).thenReturn(List.of("maiss-dev"));
        assertThat(names()).containsExactly("maiss-dev");

        // Re-stubbed rather than re-`when`-ed: the first stub throws on call.
        doReturn(List.of("ios-26ws")).when(client).listGroupPaths();
        assertThat(names()).containsExactly("ios-26ws", "maiss-dev");
    }

    @Test
    void reportsUnavailableWhenNeitherListingCanBeRead() {
        when(client.listGroupPaths()).thenThrow(new IllegalStateException("403"));
        when(client.listRealmRoleNames()).thenThrow(new IllegalStateException("403"));

        assertThat(service.list().available()).isFalse();
        assertThat(service.list().groups()).isEmpty();
    }

    @Test
    @SuppressWarnings("unchecked")
    void reportsUnavailableWithoutDirectoryAccess() {
        ObjectProvider<KeycloakAdminClient> absent = mock(ObjectProvider.class);
        when(absent.getIfAvailable()).thenReturn(null);
        KeycloakProperties props = new KeycloakProperties(
            "logos", new KeycloakProperties.Roles(List.of(), List.of()), 5, null, null, null, false);

        var withoutClient = new KeycloakGroupDirectoryService(
            absent, new KeycloakGroupLinkNormalizer(props), teamRepository);

        assertThat(withoutClient.list().available()).isFalse();
    }
}
