package de.tum.cit.aet.logos.logoswebservice.auth;

import java.util.List;
import java.util.Set;

import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.assertThat;

class KeycloakRoleMapperTest {

    private final KeycloakProperties props = new KeycloakProperties(
        "logos",
        new KeycloakProperties.Roles(List.of("itg-admin"), List.of("chair-member", "helios-admin")),
        5,
        new KeycloakProperties.Sync(false, "", "", "tum", "logos-sync", ""),
        List.of("-dev"), "logos", false);

    private final KeycloakRoleMapper mapper = new KeycloakRoleMapper(props);

    @Test
    void mapsLogosAdmin() {
        assertThat(mapper.mapRole(Set.of("itg-admin", "chair-member"))).isEqualTo("logos_admin");
    }

    @Test
    void mapsAppAdmin_anyConfiguredName() {
        assertThat(mapper.mapRole(Set.of("helios-admin", "artemis-dev"))).isEqualTo("app_admin");
        assertThat(mapper.mapRole(Set.of("chair-member"))).isEqualTo("app_admin");
    }

    @Test
    void defaultsToAppDeveloper() {
        assertThat(mapper.mapRole(Set.of("artemis-dev", "offline_access"))).isEqualTo("app_developer");
        assertThat(mapper.mapRole(Set.of())).isEqualTo("app_developer");
    }
}
