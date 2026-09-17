package de.tum.cit.aet.logos.logoswebservice.operations;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;

import static org.assertj.core.api.Assertions.assertThat;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.operations.service.RequestLogStatsRefreshService;
import de.tum.cit.aet.logos.logoswebservice.operations.service.RequestLogStatsService;

/**
 * The statistics aggregates read two sources and add them up: the hourly rollup
 * for whole hours it already covers, and log_entry for the partial head hour and
 * everything newer than the rollup's watermark.
 *
 * The property worth testing is not what either branch returns on its own, it is
 * that the answer does not depend on which one produced it. So every test here
 * asks the same question twice - once with the rollup empty, so everything comes
 * from log_entry, and once after a refresh, so the completed hours come from the
 * rollup - and demands the same numbers both times.
 *
 * That is also what makes a lagging or failed refresh safe in production: it
 * moves work back to log_entry, never numbers.
 */
@SpringBootTest
@Import(TestContainersConfig.class)
@TestPropertySource(properties = {
    "spring.liquibase.enabled=true",
    "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml",
    // "-" is Spring's disabled-cron marker: the timer never fires on its own,
    // so it cannot race the explicit refreshes below, while the scheduled entry
    // point stays callable for the test that drives it directly.
    "logos.stats.rollup.refresh-cron=-",
    "logos.auth.roles.logos-admin=itg-admin",
    "logos.auth.roles.app-admin=chair-member",
    "logos.auth.sync-debounce-minutes=5"
})
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql", "/sql/seed-stats-rollup.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-stats-rollup.sql", "/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class RequestLogStatsRollupTest {

    @Autowired RequestLogStatsService statsService;
    @Autowired RequestLogStatsRefreshService refreshService;
    @Autowired JdbcTemplate jdbc;
    @MockitoBean JwtDecoder jwtDecoder;

    /**
     * Wide enough to cover the whole seed. Both ends are anchored to the hour
     * rather than to "now": the seed places its live-tail rows at hour+1min and
     * hour+2min, so an end of now+1min would drop one of them whenever the suite
     * happens to start in the first minutes of an hour.
     */
    private static String start() {
        return Instant.now().truncatedTo(ChronoUnit.HOURS).minus(24, ChronoUnit.HOURS).toString();
    }

    private static String end() {
        return Instant.now().truncatedTo(ChronoUnit.HOURS).plus(1, ChronoUnit.HOURS)
            .minusMillis(1).toString();
    }

    /**
     * The seed rebuilds the rollup before inserting anything, so at the start of
     * every test it provably holds none of this traffic and every aggregate is
     * answered from log_entry. Asserted rather than assumed: if that ever stops
     * holding, the comparisons below would be two rollup reads agreeing with
     * each other and would pass while testing nothing.
     */
    private void assertRollupIsEmpty() {
        assertThat(rollupRowCount()).isZero();
    }

    private void populateRollup() {
        assertThat(refreshService.refreshNow()).isTrue();
        // The seed puts four rows in completed hours, so a refresh that produced
        // nothing would silently turn the "after" run into a second live run and
        // the comparison would pass without testing anything.
        assertThat(rollupRowCount()).isGreaterThan(0);
    }

    private int rollupRowCount() {
        Integer n = jdbc.queryForObject("SELECT COUNT(*) FROM log_entry_hourly_stats", Integer.class);
        return n == null ? 0 : n;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> stats(Map<String, Object> payload) {
        return (Map<String, Object>) payload.get("stats");
    }

    private Map<String, Object> query(int targetBuckets, Integer userId, Integer teamId) {
        return statsService.getRequestLogStats(start(), end(), targetBuckets, userId, teamId);
    }

    @Test
    void totals_are_the_same_whether_they_come_from_the_rollup_or_from_log_entry() {
        assertRollupIsEmpty();
        Map<String, Object> live = stats(query(24, null, null));

        populateRollup();
        Map<String, Object> merged = stats(query(24, null, null));

        assertThat(merged.get("totals")).isEqualTo(live.get("totals"));

        // And the numbers are the seed's, not an empty result that trivially
        // matches itself.
        Map<String, Object> totals = (Map<String, Object>) merged.get("totals");
        assertThat(((Number) totals.get("requests")).longValue()).isEqualTo(7L);
        assertThat(((Number) totals.get("cloudRequests")).longValue()).isEqualTo(2L);
        assertThat(((Number) totals.get("localRequests")).longValue()).isEqualTo(5L);
        // roll-002 and roll-006, one on each side of the watermark.
        assertThat(((Number) totals.get("coldStarts")).longValue()).isEqualTo(2L);
        assertThat(((Number) totals.get("totalTokens")).longValue()).isEqualTo(2800L);
    }

    @Test
    void status_counts_and_model_breakdown_are_the_same_from_either_source() {
        assertRollupIsEmpty();
        Map<String, Object> live = stats(query(24, null, null));

        populateRollup();
        Map<String, Object> merged = stats(query(24, null, null));

        assertThat(merged.get("statusCounts")).isEqualTo(live.get("statusCounts"));
        assertThat(merged.get("modelBreakdown")).isEqualTo(live.get("modelBreakdown"));

        Map<String, Object> counts = (Map<String, Object>) merged.get("statusCounts");
        assertThat(((Number) counts.get("success")).intValue()).isEqualTo(5);
        assertThat(((Number) counts.get("error")).intValue()).isEqualTo(2);
    }

    @Test
    void the_hourly_series_is_the_same_from_either_source() {
        // 24 buckets over 24 hours picks an hourly bucket, which is the smallest
        // the rollup can serve — the boundary that decides whether it is used.
        assertRollupIsEmpty();
        Map<String, Object> live = stats(query(24, null, null));

        populateRollup();
        Map<String, Object> merged = stats(query(24, null, null));

        assertThat(merged.get("timeSeries")).isEqualTo(live.get("timeSeries"));
        assertThat(merged.get("modelTimeSeries")).isEqualTo(live.get("modelTimeSeries"));

        long charted = ((List<Map<String, Object>>) merged.get("timeSeries")).stream()
            .mapToLong(b -> ((Number) b.get("total")).longValue())
            .sum();
        assertThat(charted).isEqualTo(7L);
    }

    @Test
    void a_sub_hour_bucket_bypasses_the_rollup_and_still_agrees_with_it() {
        // 1440 buckets over 24 hours asks for a minute bucket. The rollup cannot
        // express anything below an hour, so this must fall back to log_entry
        // entirely — and still count every request exactly once.
        populateRollup();
        Map<String, Object> fine = stats(query(1440, null, null));

        long charted = ((List<Map<String, Object>>) fine.get("timeSeries")).stream()
            .mapToLong(b -> ((Number) b.get("total")).longValue())
            .sum();
        assertThat(charted).isEqualTo(7L);

        Map<String, Object> totals = (Map<String, Object>) fine.get("totals");
        assertThat(((Number) totals.get("requests")).longValue()).isEqualTo(7L);
    }

    @Test
    void the_team_scope_reaches_both_sources() {
        // Five of the seven seeded rows carry team 2001, split across the
        // watermark. A scope applied to only one branch would count the other
        // branch unfiltered and come out too high.
        assertRollupIsEmpty();
        Map<String, Object> live = stats(query(24, null, 2001));

        populateRollup();
        Map<String, Object> merged = stats(query(24, null, 2001));

        assertThat(merged.get("totals")).isEqualTo(live.get("totals"));
        Map<String, Object> totals = (Map<String, Object>) merged.get("totals");
        assertThat(((Number) totals.get("requests")).longValue()).isEqualTo(5L);
    }

    @Test
    void a_range_that_does_not_start_on_the_hour_counts_its_head_hour_exactly_once() {
        // The rollup is keyed by whole hours, so a range starting mid-hour must
        // not pull in the part of that hour before its start, and must not drop
        // the part after it either. Starting 5 hours and 15 minutes back puts the
        // range boundary between the seed's two oldest rows.
        String unalignedStart = Instant.now()
            .truncatedTo(ChronoUnit.HOURS)
            .minus(13, ChronoUnit.HOURS)
            .plus(15, ChronoUnit.MINUTES)
            .toString();

        assertRollupIsEmpty();
        Map<String, Object> live = stats(
            statsService.getRequestLogStats(unalignedStart, end(), 24, null, null));

        populateRollup();
        Map<String, Object> merged = stats(
            statsService.getRequestLogStats(unalignedStart, end(), 24, null, null));

        assertThat(merged.get("totals")).isEqualTo(live.get("totals"));
        // Six of seven: roll-001 sits at the top of that hour, before the start.
        Map<String, Object> totals = (Map<String, Object>) merged.get("totals");
        assertThat(((Number) totals.get("requests")).longValue()).isEqualTo(6L);
    }

    @Test
    void a_row_that_changes_after_the_cutoff_is_corrected_by_the_next_refresh() {
        // What the rollup actually guarantees, pinned so it cannot quietly get
        // worse. The six-hour cutoff keeps a *running* request out of the rollup
        // — production's per-request timeout is 600 s, so a request cannot still
        // be in flight six hours later. Cost settlement has no such bound: it
        // can land days after the request finished, and a row it touches is
        // already inside the rollup by then.
        //
        // So this seeds a row well past the cutoff, rolls it up, changes it, and
        // asserts both halves of the contract: the change is not visible while
        // the rollup is stale, and the next refresh — a full rebuild — picks it
        // up. Bounded staleness, not a permanently wrong number.
        jdbc.update("""
            INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                                   timestamp_request, timestamp_forwarding, timestamp_response,
                                   was_cold_start, user_id, team_id)
            VALUES (9408, 'roll-late-settle', 3001, 5001, 6001, 'error',
                    date_trunc('hour', NOW()) - INTERVAL '9 hours',
                    date_trunc('hour', NOW()) - INTERVAL '9 hours' + INTERVAL '1 second',
                    date_trunc('hour', NOW()) - INTERVAL '9 hours' + INTERVAL '4 seconds',
                    false, 1001, 2001)
            """);
        try {
            populateRollup();
            Map<String, Object> rolled = (Map<String, Object>) stats(query(24, null, null)).get("statusCounts");
            assertThat(((Number) rolled.get("error")).intValue()).isEqualTo(3);

            // The row is past the cutoff, so it is in the rollup rather than the
            // live branch — which is what makes this test test anything at all.
            Integer inRollup = jdbc.queryForObject("""
                SELECT COUNT(*) FROM log_entry_hourly_stats
                 WHERE bucket_hour = date_trunc('hour', NOW()) - INTERVAL '9 hours'
                   AND result_status = 'error'
                """, Integer.class);
            assertThat(inRollup).isGreaterThan(0);

            jdbc.update("UPDATE log_entry SET result_status = 'success' WHERE id = 9408");

            // Stale until rebuilt: the rollup still carries the old status.
            Map<String, Object> stale = (Map<String, Object>) stats(query(24, null, null)).get("statusCounts");
            assertThat(((Number) stale.get("error")).intValue()).isEqualTo(3);

            // And the rebuild is what corrects it.
            assertThat(refreshService.refreshNow()).isTrue();
            Map<String, Object> fresh = (Map<String, Object>) stats(query(24, null, null)).get("statusCounts");
            assertThat(((Number) fresh.get("error")).intValue()).isEqualTo(2);
            assertThat(((Number) fresh.get("success")).intValue()).isEqualTo(6);
        } finally {
            jdbc.update("DELETE FROM log_entry WHERE id = 9408");
        }
    }

    @Test
    void a_request_still_running_at_the_refresh_stays_on_the_live_side() {
        // The case the cutoff exists for. A request forwarded inside the last six
        // hours is not rolled up however often the view is rebuilt, so when it
        // finishes the live branch reports it immediately — no refresh needed.
        jdbc.update("""
            INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                                   timestamp_request, timestamp_forwarding, timestamp_response,
                                   was_cold_start, user_id, team_id)
            VALUES (9409, 'roll-inflight', 3001, 5001, 6001, NULL,
                    date_trunc('hour', NOW()) - INTERVAL '2 hours',
                    date_trunc('hour', NOW()) - INTERVAL '2 hours' + INTERVAL '1 second',
                    NULL, false, 1001, 2001)
            """);
        try {
            populateRollup();
            Integer inRollup = jdbc.queryForObject("""
                SELECT COUNT(*) FROM log_entry_hourly_stats
                 WHERE bucket_hour = date_trunc('hour', NOW()) - INTERVAL '2 hours'
                """, Integer.class);
            assertThat(inRollup).isZero();

            Map<String, Object> before = (Map<String, Object>) stats(query(24, null, null)).get("statusCounts");
            assertThat(((Number) before.get("unknown")).intValue()).isEqualTo(1);

            jdbc.update("""
                UPDATE log_entry
                   SET result_status = 'success',
                       timestamp_response = date_trunc('hour', NOW()) - INTERVAL '2 hours' + INTERVAL '30 seconds'
                 WHERE id = 9409
                """);

            // No refresh in between: the live branch owns this row.
            Map<String, Object> after = (Map<String, Object>) stats(query(24, null, null)).get("statusCounts");
            assertThat(after.get("unknown")).isNull();
            assertThat(((Number) after.get("success")).intValue()).isEqualTo(6);
        } finally {
            jdbc.update("DELETE FROM log_entry WHERE id = 9409");
        }
    }

    @Test
    void the_scheduled_entry_point_refreshes_through_the_transaction_proxy() {
        // The scheduler calls refreshHourlyStats(), not refreshNow(). Spring
        // applies @Transactional through a proxy, so if the transactional work
        // lived on this same bean the scheduled path would reach the refresh
        // with no transaction and the transaction-scoped advisory lock would
        // guard nothing. Driving the scheduled entry point is what covers that.
        assertRollupIsEmpty();
        refreshService.refreshHourlyStats();
        assertThat(rollupRowCount()).isGreaterThan(0);
    }

    @Test
    void a_second_refresh_is_a_no_op_rather_than_a_double_count() {
        populateRollup();
        int afterFirst = rollupRowCount();
        Map<String, Object> once = stats(query(24, null, null));

        assertThat(refreshService.refreshNow()).isTrue();
        assertThat(rollupRowCount()).isEqualTo(afterFirst);
        assertThat(stats(query(24, null, null)).get("totals")).isEqualTo(once.get("totals"));
    }
}
