package de.tum.cit.aet.logos.logoswebservice.auth;

import java.util.Set;
import org.springframework.stereotype.Component;

@Component
public class KeycloakRoleMapper {

    public static final String LOGOS_ADMIN = "logos_admin";
    public static final String APP_ADMIN = "app_admin";
    public static final String APP_DEVELOPER = "app_developer";

    private final KeycloakProperties props;

    public KeycloakRoleMapper(KeycloakProperties props) {
        this.props = props;
    }

    public String mapRole(Set<String> roleNames) {
        for (String r : props.roles().logosAdmin()) {
            if (roleNames.contains(r)) return LOGOS_ADMIN;
        }
        for (String r : props.roles().appAdmin()) {
            if (roleNames.contains(r)) return APP_ADMIN;
        }
        return APP_DEVELOPER;
    }
}
