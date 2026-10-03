package de.tum.cit.aet.logos.logoswebservice.operations.service;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.security.oauth2.jwt.JwtDecoder;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Batch objects outlive their owners.
 *
 * The existing deletion paths remove API keys, users, and teams physically,
 * and a batch object is a long-lived record of cost attribution — so its
 * attribution foreign keys must let the owner go (SET NULL) instead of
 * keeping it, or a single batch created days ago would make the deletion of
 * the key, the user, or the team fail.
 */
@SpringBootTest
@Import(TestContainersConfig.class)
@TestPropertySource(properties = {
    "spring.liquibase.enabled=true",
    "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml",
    "logos.auth.roles.logos-admin=itg-admin",
    "logos.auth.roles.app-admin=chair-member",
    "logos.auth.sync-debounce-minutes=5",
    "logos.orchestrator.url=",
    "logos.orchestrator.internal-secret="
})
@Sql(scripts = {"/sql/seed-identity.sql"}, executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-identity.sql"}, executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class BatchObjectOwnerDeletionTest {

    @Autowired JdbcTemplate jdbc;
    @Autowired ApiKeyRepository apiKeyRepository;
    @Autowired TeamRepository teamRepository;
    @Autowired UserRepository userRepository;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void the_owners_of_a_batch_object_can_still_be_deleted() {
        // One batch object attributed to all three owner kinds the deletion
        // paths physically remove: the key that created it, the team it is
        // scoped to, the user behind the key.
        jdbc.update(
            "INSERT INTO batch_objects (kind, upstream_id, execution, api_key_id, team_id, user_id, status)"
                + " VALUES ('batch', 'batch_fk_test', 'logos', 3001, 2001, 1001, 'validating')");

        apiKeyRepository.deleteById(3001);
        Integer keyAttribution = jdbc.queryForObject(
            "SELECT api_key_id FROM batch_objects WHERE upstream_id = 'batch_fk_test'", Integer.class);
        assertThat(keyAttribution).isNull();

        teamRepository.deleteById(2001);
        Integer teamAttribution = jdbc.queryForObject(
            "SELECT team_id FROM batch_objects WHERE upstream_id = 'batch_fk_test'", Integer.class);
        assertThat(teamAttribution).isNull();

        // The last owner goes through the repository the service uses after
        // its managed-user guard.
        userRepository.deleteById(1001);
        Integer userAttribution = jdbc.queryForObject(
            "SELECT user_id FROM batch_objects WHERE upstream_id = 'batch_fk_test'", Integer.class);
        assertThat(userAttribution).isNull();

        // The record of what cost what survives its owners, unattributed.
        Integer remaining = jdbc.queryForObject(
            "SELECT COUNT(*) FROM batch_objects WHERE upstream_id = 'batch_fk_test'", Integer.class);
        assertThat(remaining).isEqualTo(1);

        jdbc.update("DELETE FROM batch_objects WHERE upstream_id = 'batch_fk_test'");
    }
}
