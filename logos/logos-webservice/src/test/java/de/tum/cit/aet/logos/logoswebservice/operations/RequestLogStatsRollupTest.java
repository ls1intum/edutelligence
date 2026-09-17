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
    // The scheduled refresh would race the explicit ones below.
    "logos.stats.rollup.refresh-enabled=false",
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

    /** Wide enough to cover the whole seed, ending now so the range stays live. */
    private static final String START = Instant.now().minus(24, ChronoUnit.HOURS).toString();
    private static final String END   = Instant.now().plus(1, ChronoUnit.MINUTES).toString();

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
        return statsService.getRequestLogStats(START, END, targetBuckets, userId, teamId);
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
        assertThat(((Number) totals.get("requests")).longValue()).isEqualTo(6L);
        assertThat(((Number) totals.get("cloudRequests")).longValue()).isEqualTo(2L);
        assertThat(((Number) totals.get("localRequests")).longValue()).isEqualTo(4L);
        // roll-002 and roll-006, one on each side of the watermark.
        assertThat(((Number) totals.get("coldStarts")).longValue()).isEqualTo(2L);
        assertThat(((Number) totals.get("totalTokens")).longValue()).isEqualTo(2100L);
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
        assertThat(((Number) counts.get("success")).intValue()).isEqualTo(4);
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
        assertThat(charted).isEqualTo(6L);
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
        assertThat(charted).isEqualTo(6L);

        Map<String, Object> totals = (Map<String, Object>) fine.get("totals");
        assertThat(((Number) totals.get("requests")).longValue()).isEqualTo(6L);
    }

    @Test
    void the_team_scope_reaches_both_sources() {
        // Three of the six seeded rows carry team 2001, split across the
        // watermark. A scope applied to only one branch would return four (the
        // rollup's share plus every live row) or two.
        assertRollupIsEmpty();
        Map<String, Object> live = stats(query(24, null, 2001));

        populateRollup();
        Map<String, Object> merged = stats(query(24, null, 2001));

        assertThat(merged.get("totals")).isEqualTo(live.get("totals"));
        Map<String, Object> totals = (Map<String, Object>) merged.get("totals");
        assertThat(((Number) totals.get("requests")).longValue()).isEqualTo(4L);
    }

    @Test
    void a_range_that_does_not_start_on_the_hour_counts_its_head_hour_exactly_once() {
        // The rollup is keyed by whole hours, so a range starting mid-hour must
        // not pull in the part of that hour before its start, and must not drop
        // the part after it either. Starting 5 hours and 15 minutes back puts the
        // range boundary between the seed's two oldest rows.
        String unalignedStart = Instant.now()
            .truncatedTo(ChronoUnit.HOURS)
            .minus(5, ChronoUnit.HOURS)
            .plus(15, ChronoUnit.MINUTES)
            .toString();

        assertRollupIsEmpty();
        Map<String, Object> live = stats(
            statsService.getRequestLogStats(unalignedStart, END, 24, null, null));

        populateRollup();
        Map<String, Object> merged = stats(
            statsService.getRequestLogStats(unalignedStart, END, 24, null, null));

        assertThat(merged.get("totals")).isEqualTo(live.get("totals"));
        // Five of six: roll-001 sits at the top of that hour, before the start.
        Map<String, Object> totals = (Map<String, Object>) merged.get("totals");
        assertThat(((Number) totals.get("requests")).longValue()).isEqualTo(5L);
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
