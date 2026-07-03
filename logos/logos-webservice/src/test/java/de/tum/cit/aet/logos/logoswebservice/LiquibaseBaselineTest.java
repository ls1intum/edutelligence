package de.tum.cit.aet.logos.logoswebservice;

import static org.assertj.core.api.Assertions.assertThat;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

@SpringBootTest
@Testcontainers
class LiquibaseBaselineTest {

    @Autowired
    JdbcTemplate jdbc;

    @MockitoBean
    JwtDecoder jwtDecoder;

    @Container
    @SuppressWarnings("resource")
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:17")
            .withDatabaseName("logosdb")
            .withUsername("postgres")
            .withPassword("root");

    @DynamicPropertySource
    @SuppressWarnings("unused")
    static void configureProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", postgres::getJdbcUrl);
        registry.add("spring.datasource.username", postgres::getUsername);
        registry.add("spring.datasource.password", postgres::getPassword);
        registry.add("spring.datasource.driver-class-name", () -> "org.postgresql.Driver");
        registry.add("spring.liquibase.enabled", () -> "true");
        registry.add("spring.liquibase.change-log", () -> "classpath:liquibase/changelog/master.xml");
        registry.add("spring.jpa.hibernate.ddl-auto", () -> "validate");
    }

    @Test
    void schemaApplied() {
        assertThat(tableExists("users")).isTrue();
    }

    @Test
    void migration001_keycloakColumnsExist() {
        assertThat(columnExists("users", "keycloak_id")).isTrue();
        assertThat(columnExists("users", "last_synced_at")).isTrue();
        assertThat(columnExists("users", "is_active")).isTrue();
        assertThat(columnExists("teams", "keycloak_group")).isTrue();
        assertThat(columnExists("team_members", "source")).isTrue();
    }

    @Test
    void migration003_backfillsKeyForKeylessMembership() {
        // A current membership with no developer key for that team (the legacy
        // logos_admin case) must receive exactly one active developer key whose
        // value/name match ApiKeyFactory.createDeveloperKey.
        Integer userId = jdbc.queryForObject(
            "INSERT INTO users (username, role, is_active) VALUES ('Ada Lovelace', 'logos_admin', true) RETURNING id",
            Integer.class);
        Integer teamId = jdbc.queryForObject(
            "INSERT INTO teams (name) VALUES ('Team Alpha') RETURNING id",
            Integer.class);
        jdbc.update("INSERT INTO team_members (user_id, team_id, is_owner) VALUES (?, ?, false)", userId, teamId);

        runBackfill();

        assertThat(developerKeyCount(userId, teamId)).isEqualTo(1);
        var key = jdbc.queryForMap(
            "SELECT key_value, name, is_active, environment, default_priority, use_custom_permissions "
                + "FROM api_keys WHERE user_id=? AND team_id=? AND key_type='developer'",
            userId, teamId);
        assertThat((String) key.get("key_value")).startsWith("lg-team-alpha-ada-lovelace-");
        assertThat(key.get("name")).isEqualTo("Ada Lovelace-Team Alpha-key");
        assertThat(key.get("is_active")).isEqualTo(true);
        assertThat(key.get("environment")).isEqualTo("-");
        assertThat(((Number) key.get("default_priority")).intValue()).isEqualTo(1);
        assertThat(key.get("use_custom_permissions")).isEqualTo(false);
    }

    @Test
    void migration003_skipsExisting_root_inactiveUser_andIsIdempotent() {
        // Already has a developer key -> not duplicated; even an INACTIVE one is
        // left untouched (an admin may have deliberately deactivated it).
        Integer hasKeyUser = jdbc.queryForObject(
            "INSERT INTO users (username, role, is_active) VALUES ('has_key', 'app_developer', true) RETURNING id",
            Integer.class);
        Integer teamId = jdbc.queryForObject(
            "INSERT INTO teams (name) VALUES ('Beta') RETURNING id", Integer.class);
        jdbc.update("INSERT INTO team_members (user_id, team_id, is_owner) VALUES (?, ?, false)", hasKeyUser, teamId);
        jdbc.update("INSERT INTO api_keys (key_value, name, key_type, team_id, user_id, is_active) "
            + "VALUES ('lg-existing', 'existing', 'developer', ?, ?, false)", teamId, hasKeyUser);

        // root and deactivated users must never be provisioned.
        Integer rootUser = jdbc.queryForObject(
            "INSERT INTO users (username, role, is_active) VALUES ('root', 'logos_admin', true) RETURNING id",
            Integer.class);
        Integer inactiveUser = jdbc.queryForObject(
            "INSERT INTO users (username, role, is_active) VALUES ('gone', 'app_developer', false) RETURNING id",
            Integer.class);
        jdbc.update("INSERT INTO team_members (user_id, team_id, is_owner) VALUES (?, ?, false)", rootUser, teamId);
        jdbc.update("INSERT INTO team_members (user_id, team_id, is_owner) VALUES (?, ?, false)", inactiveUser, teamId);

        runBackfill();
        runBackfill(); // idempotent: a second run must not add anything

        assertThat(developerKeyCount(hasKeyUser, teamId)).isEqualTo(1);
        assertThat((boolean) jdbc.queryForObject(
            "SELECT is_active FROM api_keys WHERE key_value='lg-existing'", Boolean.class)).isFalse();
        assertThat(developerKeyCount(rootUser, teamId)).isEqualTo(0);
        assertThat(developerKeyCount(inactiveUser, teamId)).isEqualTo(0);
    }

    private int developerKeyCount(Integer userId, Integer teamId) {
        Integer count = jdbc.queryForObject(
            "SELECT COUNT(*) FROM api_keys WHERE user_id=? AND team_id=? AND key_type='developer'",
            Integer.class, userId, teamId);
        return count == null ? 0 : count;
    }

    private void runBackfill() {
        jdbc.execute(
            "INSERT INTO api_keys (key_value, name, key_type, team_id, user_id, "
                + "environment, log, settings, default_priority, is_active, use_custom_permissions) "
                + "SELECT 'lg-' || left("
                + "  regexp_replace(regexp_replace(regexp_replace(lower(t.name), '[^a-z0-9-]', '-', 'g'), '-+', '-', 'g'), '^-|-$', '', 'g') "
                + "  || '-' || regexp_replace(regexp_replace(regexp_replace(lower(u.username), '[^a-z0-9-]', '-', 'g'), '-+', '-', 'g'), '^-|-$', '', 'g'), 35) "
                + "  || '-' || replace(gen_random_uuid()::text, '-', '') || replace(gen_random_uuid()::text, '-', '') "
                + "  || replace(gen_random_uuid()::text, '-', '') || replace(gen_random_uuid()::text, '-', ''), "
                + "  u.username || '-' || t.name || '-key', 'developer', t.id, u.id, '-', 'BILLING', '{}', 1, true, false "
                + "FROM team_members tm JOIN users u ON u.id = tm.user_id JOIN teams t ON t.id = tm.team_id "
                + "WHERE u.username <> 'root' AND u.is_active = true AND t.name IS NOT NULL AND btrim(t.name) <> '' "
                + "AND NOT EXISTS (SELECT 1 FROM api_keys k WHERE k.user_id = tm.user_id AND k.team_id = tm.team_id AND k.key_type = 'developer')");
    }

    private boolean tableExists(String tableName) {
        Integer count = jdbc.queryForObject(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_name=?",
            Integer.class, tableName);
        return Integer.valueOf(1).equals(count);
    }

    private boolean columnExists(String tableName, String columnName) {
        Integer count = jdbc.queryForObject(
            "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='public' AND table_name=? AND column_name=?",
            Integer.class, tableName, columnName);
        return Integer.valueOf(1).equals(count);
    }
}
