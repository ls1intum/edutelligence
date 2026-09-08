package de.tum.cit.aet.logos.logoswebservice.configuration;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import java.util.Map;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.common.ConflictException;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.AddModelRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelService;

/**
 * Concurrency coverage for the shared, case-insensitive model-name/alias
 * namespace. The checks in {@code ModelService} (model name vs. alias, alias
 * vs. model name, alias vs. alias) are plain reads that hold no locks, so
 * under READ COMMITTED two concurrent requests can pass both checks and
 * commit conflicting rows unless the namespace is serialized. These tests
 * run against the real Postgres container, so the advisory-lock behaviour
 * and the unique-index fallback are exercised end to end.
 */
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestContainersConfig.class)
@TestPropertySource(properties = {
    "spring.liquibase.enabled=true",
    "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml",
    "logos.auth.roles.logos-admin=itg-admin",
    "logos.auth.roles.app-admin=chair-member",
    "logos.auth.sync-debounce-minutes=5"
})
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class ModelAliasNamespaceConcurrencyTest {

    @Autowired ModelService modelService;
    @Autowired JdbcTemplate jdbc;
    @Autowired PlatformTransactionManager transactionManager;

    @MockitoBean
    JwtDecoder jwtDecoder;

    @Test
    void concurrentModelNameAndAliasAssignmentCommitsAtMostOne() throws Exception {
        // One thread creates a model, the other assigns the same string as an
        // alias to a different model. Whatever commits first makes the other
        // request's validation fail, so the namespace can never end up holding
        // both.
        String modelName = "race-conf-model";
        String otherName = "race-other-model";

        CyclicBarrier barrier = new CyclicBarrier(2);
        try (ExecutorService pool = Executors.newFixedThreadPool(2)) {
            Future<Map<String, Object>> addModel = pool.submit(
                () -> {
                    barrier.await(10, TimeUnit.SECONDS);
                    return modelService.addModel(
                        new AddModelRequestDTO(modelName, null, null, null, null, null, null, List.of()));
                });
            Future<Map<String, Object>> addAlias = pool.submit(
                () -> {
                    barrier.await(10, TimeUnit.SECONDS);
                    return modelService.addModel(
                        new AddModelRequestDTO(otherName, null, null, null, null, null, null, List.of(modelName)));
                });

            int failures = 0;
            for (Future<Map<String, Object>> future : List.of(addModel, addAlias)) {
                try {
                    future.get(30, TimeUnit.SECONDS);
                } catch (ExecutionException e) {
                    failures++;
                }
            }
            assertThat(failures).as("exactly one of the conflicting assignments may commit").isEqualTo(1);
        }

        long modelCount = jdbc.queryForObject("SELECT COUNT(*) FROM models WHERE name = ?", Long.class, modelName);
        long aliasCount = jdbc.queryForObject(
            "SELECT COUNT(*) FROM model_aliases WHERE LOWER(alias) = LOWER(?)", Long.class, modelName);
        assertThat(modelCount + aliasCount).as("the name may exist as model or alias, not both").isEqualTo(1);
    }

    @Test
    void aliasInsertLosingTheUniqueIndexRaceSurfacesAsConflict() throws Exception {
        // A rival transaction holds the same alias uncommitted: the service's
        // duplicate check cannot see it under READ COMMITTED, so the insert
        // blocks on the unique index until the rival commits — and the loser
        // must surface a client-facing conflict (409), not a 500.
        String alias = "race-dup-alias";
        Map<String, Object> host = modelService.addModel(
            new AddModelRequestDTO("race-host-model", null, null, null, null, null, null, List.of()));

        CountDownLatch rivalInserted = new CountDownLatch(1);
        CountDownLatch releaseRival = new CountDownLatch(1);
        TransactionTemplate rivalTx = new TransactionTemplate(transactionManager);
        try (ExecutorService rivalPool = Executors.newSingleThreadExecutor();
             ExecutorService servicePool = Executors.newSingleThreadExecutor()) {
            Future<Integer> rival = rivalPool.submit(() -> rivalTx.execute(status -> {
                jdbc.update("INSERT INTO model_aliases (model_id, alias) VALUES (?, ?)",
                    host.get("model_id"), alias);
                rivalInserted.countDown();
                try {
                    if (!releaseRival.await(30, TimeUnit.SECONDS)) {
                        status.setRollbackOnly();
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    status.setRollbackOnly();
                }
                return 1;
            }));

            assertThat(rivalInserted.await(10, TimeUnit.SECONDS)).isTrue();

            Future<Map<String, Object>> service = servicePool.submit(
                () -> modelService.addModel(
                    new AddModelRequestDTO("race-host-second", null, null, null, null, null, null, List.of(alias))));

            // Wait until the service's insert is demonstrably blocked on the
            // rival's uncommitted row, then let the rival win the race.
            long deadline = System.currentTimeMillis() + 15_000;
            while (System.currentTimeMillis() < deadline) {
                Long waiting = jdbc.queryForObject(
                    "SELECT COUNT(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND query ILIKE '%model_aliases%'",
                    Long.class);
                if (waiting != null && waiting > 0) {
                    break;
                }
                Thread.sleep(50);
            }
            releaseRival.countDown();
            rival.get(30, TimeUnit.SECONDS);

            Exception serviceError = null;
            try {
                service.get(30, TimeUnit.SECONDS);
            } catch (ExecutionException e) {
                serviceError = e.getCause() instanceof Exception ex ? ex : e;
            }
            assertThat(serviceError).isInstanceOf(ConflictException.class);
        }

        long aliasCount = jdbc.queryForObject(
            "SELECT COUNT(*) FROM model_aliases WHERE LOWER(alias) = LOWER(?)", Long.class, alias);
        assertThat(aliasCount).as("the alias is committed exactly once, by the rival").isEqualTo(1);
        Long secondHost = jdbc.queryForObject(
            "SELECT COUNT(*) FROM models WHERE name = 'race-host-second'", Long.class);
        assertThat(secondHost).as("the losing service transaction rolled back").isZero();
    }
}
