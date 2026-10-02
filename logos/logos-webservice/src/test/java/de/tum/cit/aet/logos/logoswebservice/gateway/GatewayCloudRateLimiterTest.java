package de.tum.cit.aet.logos.logoswebservice.gateway;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicInteger;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.web.server.ResponseStatusException;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.DockerImageName;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;

/**
 * Shared cloud RPM/TPM via Redis — every webservice replica sees the same window.
 */
@SpringBootTest
@Testcontainers
class GatewayCloudRateLimiterTest {

    @Autowired
    JdbcTemplate jdbc;

    @Autowired
    GatewayCloudRateLimiter rateLimiter;

    @Autowired
    StringRedisTemplate redis;

    @MockitoBean
    JwtDecoder jwtDecoder;

    @Container
    @SuppressWarnings("resource")
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:17")
            .withDatabaseName("logosdb")
            .withUsername("postgres")
            .withPassword("root");

    @Container
    @SuppressWarnings("resource")
    static GenericContainer<?> redisContainer = new GenericContainer<>(DockerImageName.parse("redis:7-alpine"))
            .withExposedPorts(6379);

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
        registry.add("spring.data.redis.host", redisContainer::getHost);
        registry.add("spring.data.redis.port", () -> redisContainer.getMappedPort(6379));
        registry.add("logos.gateway.budget-reservation-reconcile-seconds", () -> "3600");
    }

    private static final AtomicInteger SEQ = new AtomicInteger(1);
    private static final byte[] BODY =
        "{\"model\":\"m\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}".getBytes(StandardCharsets.UTF_8);

    @BeforeEach
    void flushRedis() {
        var factory = redis.getConnectionFactory();
        if (factory == null) {
            return;
        }
        try (var connection = factory.getConnection()) {
            connection.serverCommands().flushAll();
        }
    }

    @Test
    void noLimitsConfigured_isANoOp() {
        GatewayKey key = seedKey(null, null);
        assertThatCode(() -> rateLimiter.enforce(key, BODY)).doesNotThrowAnyException();
    }

    @Test
    void sharedRpm_rejectsOnceTheWindowIsFull() {
        GatewayKey key = seedKey(2, null);
        assertThatCode(() -> rateLimiter.enforce(key, BODY)).doesNotThrowAnyException();
        assertThatCode(() -> rateLimiter.enforce(key, BODY)).doesNotThrowAnyException();
        assertThatThrownBy(() -> rateLimiter.enforce(key, BODY))
            .isInstanceOf(ResponseStatusException.class)
            .satisfies(e -> assertThatStatus((ResponseStatusException) e, HttpStatus.TOO_MANY_REQUESTS))
            .hasMessageContaining("RPM limit reached");
    }

    @Test
    void rpmOnly_doesNotRecordTpmClaims() {
        GatewayKey key = seedKey(10, null);
        assertThatCode(() -> rateLimiter.enforce(key, BODY)).doesNotThrowAnyException();
        assertThat(redis.opsForZSet().zCard("gw:tpm:" + key.id())).isZero();
        assertThat(redis.opsForValue().get("gw:tpm:sum:" + key.id())).isNull();
    }

    @Test
    void rpmOnly_prunesExpiredTpmClaimsAndReducesSum() {
        // Prior TPM-enabled admissions left claims + a running sum. While TPM is
        // disabled, RPM admissions must still subtract expired claim tokens from
        // the sum — otherwise re-enabling TPM false-429s on the stale excess.
        GatewayKey key = seedKey(10, null);
        String tpmKey = "gw:tpm:" + key.id();
        String tpmSumKey = "gw:tpm:sum:" + key.id();
        redis.opsForZSet().add(tpmKey, "stale-a:400", 1.0);
        redis.opsForZSet().add(tpmKey, "stale-b:100", 2.0);
        redis.opsForValue().set(tpmSumKey, "500");

        assertThatCode(() -> rateLimiter.enforce(key, BODY)).doesNotThrowAnyException();

        assertThat(redis.opsForZSet().zCard(tpmKey)).isZero();
        assertThat(redis.opsForValue().get(tpmSumKey)).isEqualTo("0");
        // RPM-only must not write new TPM claims.
        assertThat(redis.opsForZSet().range(tpmKey, 0, -1)).isNullOrEmpty();
    }

    @Test
    void sharedTpm_rejectsWhenEstimatesWouldExceedTheLimit() {
        // BODY estimate is body.length/4; pick a limit that admits two then refuses.
        int estimate = GatewayCloudRateLimiter.estimateTokens(BODY);
        GatewayKey key = seedKey(null, estimate * 2);
        assertThatCode(() -> rateLimiter.enforce(key, BODY)).doesNotThrowAnyException();
        assertThatCode(() -> rateLimiter.enforce(key, BODY)).doesNotThrowAnyException();
        assertThatThrownBy(() -> rateLimiter.enforce(key, BODY))
            .isInstanceOf(ResponseStatusException.class)
            .satisfies(e -> assertThatStatus((ResponseStatusException) e, HttpStatus.TOO_MANY_REQUESTS))
            .hasMessageContaining("TPM limit reached");
    }

    private static void assertThatStatus(ResponseStatusException e, HttpStatus expected) {
        org.assertj.core.api.Assertions.assertThat(e.getStatusCode()).isEqualTo(expected);
    }

    private GatewayKey seedKey(Integer rpm, Integer tpm) {
        int teamId = jdbc.queryForObject(
            "INSERT INTO teams (name, default_cloud_rpm_limit, default_cloud_tpm_limit, "
            + "default_monthly_budget_micro_cents, team_monthly_budget_micro_cents) "
            + "VALUES (?, NULL, NULL, 1000000000, 1000000000) RETURNING id",
            Integer.class, "t-" + SEQ.getAndIncrement());
        String settings;
        if (rpm == null && tpm == null) {
            settings = "{}";
        } else if (rpm != null && tpm != null) {
            settings = "{\"cloud_rpm_limit\":" + rpm + ",\"cloud_tpm_limit\":" + tpm + "}";
        } else if (rpm != null) {
            settings = "{\"cloud_rpm_limit\":" + rpm + "}";
        } else {
            settings = "{\"cloud_tpm_limit\":" + tpm + "}";
        }
        int apiKeyId = jdbc.queryForObject(
            "INSERT INTO api_keys (key_value, name, team_id, key_type, log, settings) "
            + "VALUES (?, ?, ?, 'application'::api_key_type_enum, 'BILLING'::logging_enum, "
            + "CAST(? AS jsonb)) RETURNING id",
            Integer.class, "lg-" + SEQ.getAndIncrement(), "k-" + SEQ.get(), teamId, settings);
        return new GatewayKey(apiKeyId, "lg-x", "k", ApiKeyType.application,
            teamId, null, "test", false, settings, 0, "BILLING");
    }
}
