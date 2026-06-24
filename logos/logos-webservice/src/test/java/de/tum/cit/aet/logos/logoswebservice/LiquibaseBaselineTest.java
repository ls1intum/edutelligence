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
