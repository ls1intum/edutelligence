package de.tum.cit.aet.logos.logoswebservice.identity.entity;

public enum Role {
    APP_DEVELOPER(Names.APP_DEVELOPER),
    APP_ADMIN(Names.APP_ADMIN),
    LOGOS_ADMIN(Names.LOGOS_ADMIN);

    public static final class Names {
        public static final String APP_DEVELOPER = "app_developer";
        public static final String APP_ADMIN = "app_admin";
        public static final String LOGOS_ADMIN = "logos_admin";

        private Names() {
        }
    }

    private final String value;

    Role(String value) {
        this.value = value;
    }

    public String getValue() {
        return value;
    }

    public boolean matches(String role) {
        return value.equals(role);
    }
}
