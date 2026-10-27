package de.tum.cit.aet.logos.logoswebservice;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import java.sql.DriverManager;
import java.util.List;
import java.util.UUID;
import liquibase.Contexts;
import liquibase.LabelExpression;
import liquibase.Liquibase;
import liquibase.Scope;
import liquibase.changelog.FastCheckService;
import liquibase.database.jvm.JdbcConnection;
import liquibase.resource.ClassLoaderResourceAccessor;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;
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
    void nightlySchedulesCoexistWithCentralProfilesAndUseConsolidatedMigrationIds() {
        assertThat(tableExists("model_profiles")).isTrue();
        assertThat(tableExists("model_calibrations")).isTrue();
        assertThat(tableExists("nightly_benchmarks")).isTrue();
        assertThat(tableExists("maintenance_calibration")).isTrue();
        assertThat(tableExists("maintenance_benchmark")).isTrue();
        assertThat(columnExists("nightly_benchmarks", "recovery")).isTrue();
        assertThat(jdbc.queryForList(
            "SELECT id FROM databasechangelog WHERE filename = ? AND author = 'logos' ORDER BY orderexecuted",
            String.class, "liquibase/changelog/065_nightly_benchmarks.xml"))
            .containsExactly("065-nightly-benchmarks", "065-maintenance-calibration", "065-parallel-maintenance");
    }

    @ParameterizedTest
    @ValueSource(ints = {0, 2, 3})
    void consolidatedMaintenanceChangelogUpgradesAndRollsBack(int legacyChangeSets) throws Exception {
        String schema = "maintenance_upgrade_" + UUID.randomUUID().toString().replace("-", "");
        jdbc.execute("CREATE SCHEMA " + schema);
        try (var connection = DriverManager.getConnection(
                postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
                var resources = new ClassLoaderResourceAccessor();
                var liquibase = new Liquibase("liquibase/changelog/065_nightly_benchmarks.xml",
                    resources, new JdbcConnection(connection))) {
            connection.setSchema(schema);
            liquibase.getDatabase().setDefaultSchemaName(schema);
            liquibase.getDatabase().setLiquibaseSchemaName(schema);
            var isolated = new JdbcTemplate(new SingleConnectionDataSource(connection, true));
            isolated.execute("CREATE TABLE jobs (id integer PRIMARY KEY, request_payload jsonb)");
            isolated.execute("INSERT INTO jobs VALUES (1, '{\"provider_id\":42}')");
            connection.commit();
            liquibase.update(2, new Contexts(), new LabelExpression());
            isolated.execute("INSERT INTO nightly_benchmarks (model_provider_id, enabled) VALUES (31, true)");
            isolated.execute("INSERT INTO maintenance_calibration (provider_id, token) VALUES (42, 'existing')");
            isolated.execute("INSERT INTO maintenance_benchmark (job_id) VALUES (1)");
            connection.commit();
            if (legacyChangeSets == 3) {
                liquibase.update(new Contexts(), new LabelExpression());
            }
            if (legacyChangeSets > 0) {
                // Reproduce the history identities recorded by earlier deployments of this schema.
                isolated.execute("""
                    UPDATE databasechangelog SET
                        id = CASE id
                            WHEN '065-nightly-benchmarks' THEN '057-nightly-benchmarks'
                            WHEN '065-maintenance-calibration' THEN '061-maintenance-calibration'
                            WHEN '065-parallel-maintenance' THEN '067-parallel-maintenance' END,
                        filename = CASE id
                            WHEN '065-nightly-benchmarks' THEN 'liquibase/changelog/057_nightly_benchmarks.xml'
                            WHEN '065-maintenance-calibration' THEN 'liquibase/changelog/061_maintenance_calibration.xml'
                            WHEN '065-parallel-maintenance' THEN 'liquibase/changelog/067_parallel_maintenance.xml' END
                    """);
                connection.commit();
            }
            var oldHistory = isolated.queryForList("SELECT * FROM databasechangelog WHERE id NOT LIKE '065-%' ORDER BY id");

            liquibase.update(new Contexts(), new LabelExpression());
            liquibase.update(new Contexts(), new LabelExpression());

            assertThat(isolated.queryForObject("SELECT count(*) FROM databasechangelog", Integer.class))
                .isEqualTo(3 + legacyChangeSets);
            assertThat(isolated.queryForList("SELECT * FROM databasechangelog WHERE id NOT LIKE '065-%' ORDER BY id"))
                .isEqualTo(oldHistory);
            assertThat(isolated.queryForObject("SELECT enabled FROM nightly_benchmarks", Boolean.class)).isTrue();
            assertThat(isolated.queryForObject("SELECT token FROM maintenance_calibration", String.class)).isEqualTo("existing");
            assertThat(isolated.queryForObject("SELECT provider_id FROM maintenance_benchmark", Integer.class)).isEqualTo(42);
            isolated.execute("INSERT INTO maintenance_calibration (provider_id, token) VALUES (43, 'parallel')");
            isolated.execute("INSERT INTO maintenance_benchmark (job_id, provider_id) VALUES (2, 43)");
            connection.commit();

            assertThatThrownBy(() -> liquibase.rollback(1, new Contexts(), new LabelExpression()))
                .hasMessageContaining("maintenance_benchmark_pkey");
            assertThat(isolated.queryForObject("SELECT count(*) FROM maintenance_benchmark WHERE provider_id IS NOT NULL",
                Integer.class)).isEqualTo(2);
            isolated.execute("DELETE FROM maintenance_benchmark WHERE job_id = 2");
            connection.commit();
            assertThatThrownBy(() -> liquibase.rollback(1, new Contexts(), new LabelExpression()))
                .hasMessageContaining("maintenance_calibration_pkey");
            assertThat(isolated.queryForObject("SELECT provider_id FROM maintenance_benchmark", Integer.class)).isEqualTo(42);
            isolated.execute("DELETE FROM maintenance_calibration WHERE provider_id = 43");
            connection.commit();

            liquibase.rollback(1, new Contexts(), new LabelExpression());
            assertThat(isolated.queryForObject("SELECT token FROM maintenance_calibration", String.class)).isEqualTo("existing");
            assertThat(isolated.queryForList("""
                SELECT pg_get_constraintdef(oid) FROM pg_constraint
                WHERE connamespace = ?::regnamespace AND contype = 'p'
                AND conrelid IN ('maintenance_calibration'::regclass, 'maintenance_benchmark'::regclass)
                """, String.class, schema)).containsExactlyInAnyOrder("PRIMARY KEY (singleton)", "PRIMARY KEY (singleton)");
            liquibase.rollback(2, new Contexts(), new LabelExpression());
            assertThat(isolated.queryForObject("SELECT count(*) FROM information_schema.tables"
                + " WHERE table_schema = ? AND table_name IN ('nightly_benchmarks', 'maintenance_calibration', 'maintenance_benchmark')",
                Integer.class, schema)).isZero();
            // Use a fresh Liquibase instance, as on application restart after rollback.
            Scope.getCurrentScope().getSingleton(FastCheckService.class).clearCache();
            try (var restartConnection = DriverManager.getConnection(
                    postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
                    var restarted = new Liquibase("liquibase/changelog/065_nightly_benchmarks.xml",
                        resources, new JdbcConnection(restartConnection))) {
                restartConnection.setSchema(schema);
                restarted.getDatabase().setDefaultSchemaName(schema);
                restarted.getDatabase().setLiquibaseSchemaName(schema);
                restarted.update(new Contexts(), new LabelExpression());
            }
            assertThat(isolated.queryForObject("SELECT count(*) FROM nightly_benchmarks", Integer.class)).isZero();
        } finally {
            jdbc.execute("DROP SCHEMA " + schema + " CASCADE");
        }
    }

    @Test
    void migration045_teamRepositoriesExist() {
        assertThat(tableExists("team_repositories")).isTrue();
        assertThat(columnExists("team_repositories", "repo_url")).isTrue();
        assertThat(columnExists("team_repositories", "repo_slug")).isTrue();
        assertThat(columnExists("team_repositories", "branch")).isTrue();
        assertThat(columnExists("team_repositories", "paths")).isTrue();
        Integer uniqueIndex = jdbc.queryForObject(
            "SELECT COUNT(*) FROM pg_indexes WHERE schemaname='public' AND indexname=?",
            Integer.class, "uq_team_repositories_team_slug");
        assertThat(uniqueIndex).isEqualTo(1);
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
    void providerPerformanceIndexExists() {
        Integer count = jdbc.queryForObject(
            "SELECT COUNT(*) FROM pg_indexes WHERE schemaname='public' AND indexname=?",
            Integer.class, "idx_log_entry_performance_window");
        assertThat(count).isEqualTo(1);
    }

    @Test
    void migration027_rateLimitAdmittedColumnAndForwardingIndexExist() {
        // The /me/keys usage window filters log_entry on both of these:
        // rejected requests are excluded via the column, and the
        // (api_key_id, timestamp_forwarding) range needs its index.
        assertThat(columnExists("log_entry", "rate_limit_admitted")).isTrue();
        Integer count = jdbc.queryForObject(
            "SELECT COUNT(*) FROM pg_indexes WHERE schemaname='public' AND indexname=?",
            Integer.class, "idx_log_entry_api_key_timestamp_forwarding");
        assertThat(count).isEqualTo(1);
    }

    @Test
    void migration028_rateLimitCompletionResponseIndexExists() {
        // The completion half of the /me/keys usage window filters log_entry
        // on timestamp_response per key; it needs its own
        // (api_key_id, timestamp_response) index, since the 027 forwarding
        // index cannot satisfy the `timestamp_response >= :since` OR disjunct.
        Integer count = jdbc.queryForObject(
            "SELECT COUNT(*) FROM pg_indexes WHERE schemaname='public' AND indexname=?",
            Integer.class, "idx_log_entry_api_key_timestamp_response");
        assertThat(count).isEqualTo(1);
    }

    @Test
    void migration042_modelNameColumnsAndOrphanGrainIndexExist() {
        // Deleting a model captures its name on the usage rows so the per-model
        // statistics survive; the rollup grain must tell orphans apart by that
        // name, so the unique grain index carries the column.
        assertThat(columnExists("log_entry", "model_name")).isTrue();
        assertThat(columnExists("log_entry_hourly_stats", "model_name")).isTrue();
        Integer count = jdbc.queryForObject(
            "SELECT COUNT(*) FROM pg_indexes"
            + " WHERE schemaname='public' AND indexname='ux_log_entry_hourly_stats_grain'"
            + " AND indexdef LIKE '%model_name%'",
            Integer.class);
        assertThat(count).isEqualTo(1);
        // A delete can outlive the rollup pass's write lag, in which case the
        // updated_at stamp alone is never re-scanned; the delete's queue of
        // affected hours is what the pass falls back on.
        assertThat(tableType("log_entry_rollup_dirty_hours")).isEqualTo("BASE TABLE");
    }

    @Test
    void migration052_recommendationTierColumnsRenamedToSlo() {
        // Postgres rejects combining RENAME COLUMN operations in one
        // ALTER TABLE, so 052 issues one rename per statement; on a fresh
        // database the SLO names must exist and the SLA names be gone.
        assertThat(columnExists("ai_llm_call_recommendations", "recommended_slo")).isTrue();
        assertThat(columnExists("ai_llm_call_recommendations", "confirmed_slo")).isTrue();
        assertThat(columnExists("ai_llm_call_recommendations", "recommended_sla")).isFalse();
        assertThat(columnExists("ai_llm_call_recommendations", "confirmed_sla")).isFalse();
    }

    @Test
    void migration055_batchObjectsLogLevelExists() {
        // Per-request logging consent for batches that outlive their creating
        // request; NULL means the create sent no logos-logging header.
        assertThat(columnExists("batch_objects", "log_level")).isTrue();
    }

    @Test
    void migration056_teamFullPrivacyIndexServesActivityExists() {
        // The activity-tab FULL-privacy EXISTS must seek the partial
        // (team_id, timestamp_request) index rather than walk every BILLING
        // row in the selected window via idx_log_entry_team_ts_request.
        Integer count = jdbc.queryForObject(
            "SELECT COUNT(*) FROM pg_indexes"
                + " WHERE schemaname='public' AND indexname=?"
                + " AND indexdef LIKE '%privacy_level%FULL%'",
            Integer.class, "idx_log_entry_team_full_privacy");
        assertThat(count).isEqualTo(1);

        String plan = String.join("\n", jdbc.queryForList(
            "EXPLAIN SELECT EXISTS ("
                + " SELECT 1 FROM log_entry le"
                + " WHERE le.team_id = 1"
                + "   AND le.privacy_level = 'FULL'"
                + "   AND le.timestamp_request BETWEEN now() - interval '7 days' AND now()"
                + ")",
            String.class));
        assertThat(plan).contains("idx_log_entry_team_full_privacy");
    }

    @Test
    void migration029_providerSnapshotsTableRenamed() {
        // The physical table carries the engine-neutral name now...
        assertThat(tableType("provider_snapshots")).isEqualTo("BASE TABLE");
        // ...while the pre-rename name survives exactly one release as a
        // pass-through view, so an orchestrator rolled back to the previous
        // release can still write it (see migration 029's compatibility view).
        assertThat(tableType("ollama_provider_snapshots")).isEqualTo("VIEW");
    }

    @Test
    void migration029_compatibilityViewMirrorsTheRenamedTable() {
        // The view is a plain SELECT * over the renamed table, so it must
        // expose every column the previous release wrote: the identifier, the
        // base metrics, and the richer runtime/scheduler payloads added later.
        // A rolled-back orchestrator INSERTs through this view.
        assertThat(columns("ollama_provider_snapshots"))
                .contains("id", "provider_id", "snapshot_ts", "loaded_models", "runtime_payload", "scheduler_signals");
    }

    @Test
    void migration030_allowsStartWithoutOllamaTypedProviders() {
        // The 030 gate must be a no-op on a clean schema (the provider_type
        // enum makes legacy local-provider rows impossible) — reaching this test already
        // proves the changelog ran to the end.
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM providers", Integer.class)).isZero();
    }

    @Test
    void migration057_requestedModelsAndVotesTablesExist() {
        // The model-request voting feature: a registry of requested models
        // (one row per model, unique on the lower-cased name) plus the votes
        // (one row per voter, unique on the (model, user) pair so each user gets
        // exactly one vote per model).
        assertThat(tableExists("requested_models")).isTrue();
        assertThat(columnExists("requested_models", "id")).isTrue();
        assertThat(columnExists("requested_models", "name")).isTrue();
        assertThat(tableExists("requested_model_votes")).isTrue();
        assertThat(columnExists("requested_model_votes", "id")).isTrue();
        assertThat(columnExists("requested_model_votes", "requested_model_id")).isTrue();
        assertThat(columnExists("requested_model_votes", "user_id")).isTrue();
        for (String indexName : new String[] {
            "uq_requested_models_name_lower",
            "uq_requested_model_votes_model_user",
        }) {
            Integer count = jdbc.queryForObject(
                "SELECT COUNT(*) FROM pg_indexes WHERE schemaname='public' AND indexname=?",
                Integer.class, indexName);
            assertThat(count).as("index %s", indexName).isEqualTo(1);
        }
    }

    @Test
    void migration067_requestedModelIsGatedColumnExists() {
        // The decisive Hugging Face gating verdict a requested model carries
        // (true when the Hub rejects the repository as gated); null until the
        // precheck has produced a verdict, so the column must be nullable.
        assertThat(columnExists("requested_models", "is_gated")).isTrue();
    }

    @Test
    void migration067_requestedModelFirstRequestingTeamColumnExists() {
        // The team that first requested the model; null on rows that predate
        // the column, so it must be nullable.
        assertThat(columnExists("requested_models", "first_requesting_team")).isTrue();
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
        // The 002 backfill SQL writes the legacy default 1, which is preserved
        // as-is (changeset 039 deliberately does not rewrite existing rows;
        // 1 keeps acting as an explicit LOW override until an admin resets it).
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

    @Test
    void migration039_preservesExistingPrioritiesAndUnsetsFutureDefaults() {
        // A stored 1 on a developer key is ambiguous: legacy factory/backfill
        // default or a deliberately pinned LOW override. There is no reliable
        // provenance, so 039 must leave every existing row untouched (a bulk
        // reset would silently lift pinned-LOW keys to team/policy priority
        // without owner intent) and only re-point the column default so
        // future raw inserts use the "unset" marker 0.
        Integer userId = jdbc.queryForObject(
            "INSERT INTO users (username, role, is_active) VALUES ('key-reset', 'app_developer', true) RETURNING id",
            Integer.class);
        Integer teamId = jdbc.queryForObject(
            "INSERT INTO teams (name) VALUES ('Reset') RETURNING id", Integer.class);
        jdbc.update("INSERT INTO api_keys (key_value, name, key_type, team_id, user_id, default_priority, is_active) "
            + "VALUES ('lg-pinned-low-dev', 'pinned low dev', 'developer', ?, ?, 1, true)", teamId, userId);
        jdbc.update("INSERT INTO api_keys (key_value, name, key_type, team_id, user_id, default_priority, is_active) "
            + "VALUES ('lg-explicit-dev', 'explicit dev', 'developer', ?, ?, 5, true)", teamId, userId);
        jdbc.update("INSERT INTO api_keys (key_value, name, key_type, team_id, user_id, default_priority, is_active) "
            + "VALUES ('lg-app-key', 'app key', 'application', ?, ?, 1, true)", teamId, userId);

        runMigration039();

        // Existing values survive, including a developer key pinned to LOW.
        assertThat(keyPriority("lg-pinned-low-dev")).isEqualTo(1);
        assertThat(keyPriority("lg-explicit-dev")).isEqualTo(5);
        assertThat(keyPriority("lg-app-key")).isEqualTo(1);

        // A new row that omits default_priority gets the new default 0.
        jdbc.update("INSERT INTO api_keys (key_value, name, key_type, team_id, user_id, is_active) "
            + "VALUES ('lg-default-dev', 'default dev', 'developer', ?, ?, true)", teamId, userId);
        assertThat(keyPriority("lg-default-dev")).isEqualTo(0);
    }

    private int keyPriority(String keyValue) {
        Number priority = jdbc.queryForObject(
            "SELECT default_priority FROM api_keys WHERE key_value=?", Number.class, keyValue);
        return priority.intValue();
    }

    private void runMigration039() {
        jdbc.update("ALTER TABLE api_keys ALTER COLUMN default_priority SET DEFAULT 0");
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

    private String tableType(String tableName) {
        // Distinguishes a base table from a view: information_schema.tables
        // lists both, tagged by table_type ('BASE TABLE' vs 'VIEW').
        return jdbc.queryForObject(
            "SELECT table_type FROM information_schema.tables WHERE table_schema='public' AND table_name=?",
            String.class, tableName);
    }

    private List<String> columns(String tableName) {
        return jdbc.queryForList(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=? "
                + "ORDER BY ordinal_position",
            String.class, tableName);
    }
}
