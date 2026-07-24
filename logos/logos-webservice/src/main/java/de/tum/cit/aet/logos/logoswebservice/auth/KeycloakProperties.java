package de.tum.cit.aet.logos.logoswebservice.auth;

import java.util.List;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "logos.auth")
public record KeycloakProperties(
    String clientId,
    Roles roles,
    int syncDebounceMinutes,
    Sync sync,
    List<String> teamRoleSuffixes,
    String audience,
    boolean autoProvisionTeams
) {
    public KeycloakProperties {
        if (teamRoleSuffixes == null) {
            teamRoleSuffixes = List.of("-dev", "-team", "-group", "-member");
        }
        if (audience == null || audience.isBlank()) {
            audience = clientId;
        }
        if (roles == null) {
            roles = new Roles(List.of(), List.of());
        } else {
            List<String> la = roles.logosAdmin() != null ? roles.logosAdmin() : List.of();
            List<String> aa = roles.appAdmin() != null ? roles.appAdmin() : List.of();
            roles = new Roles(la, aa);
        }
    }

    public record Roles(List<String> logosAdmin, List<String> appAdmin) {}

    public record Sync(
        boolean enabled,
        String cron,
        String adminBaseUrl,
        String realm,
        String clientId,
        String clientSecret
    ) {}
}
