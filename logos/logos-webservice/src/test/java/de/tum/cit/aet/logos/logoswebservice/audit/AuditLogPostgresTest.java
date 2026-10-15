package de.tum.cit.aet.logos.logoswebservice.audit;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

/** The audit SQL against a real Postgres: jsonb casts, nullable filters, paging. */
@SpringBootTest
@Testcontainers
class AuditLogPostgresTest {

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

    @MockitoBean
    JwtDecoder jwtDecoder;

    @Autowired
    AuditLogService service;

    @Test
    void recordedChangeIsReadBackFilteredAndPaged() {
        int team = 987_001;
        service.record("team.limits_updated", "team", team, team,
            Map.of("team_monthly_budget_micro_cents", 1L), Map.of("team_monthly_budget_micro_cents", 2L));
        service.record("team.provider_budget_removed", "team_provider_budget", team + "/4", team,
            Map.of("sponsored", true), Map.of("sponsored", false));
        service.record("api_key.log_level_changed", "api_key", 9, 987_002,
            Map.of("log", "BILLING"), Map.of("log", "FULL"));

        List<Map<String, Object>> mine = service.list(team, null, 50);
        assertThat(mine).extracting(r -> r.get("action"))
            .containsExactly("team.provider_budget_removed", "team.limits_updated");
        assertThat(mine.get(1).get("before_state")).isEqualTo(Map.of("team_monthly_budget_micro_cents", 1));
        assertThat(mine.get(1).get("after_state")).isEqualTo(Map.of("team_monthly_budget_micro_cents", 2));
        assertThat(mine.get(1).get("occurred_at")).isNotNull();

        long newestId = ((Number) mine.get(0).get("id")).longValue();
        assertThat(service.list(team, newestId, 50)).hasSize(1);
        assertThat(service.list(null, null, 1)).hasSize(1);
    }
}
