package de.tum.cit.aet.logos.logoswebservice.operations.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;

/**
 * Keeps {@code log_entry_hourly_stats} — the rollup behind the statistics page —
 * current.
 *
 * Hourly, because the view holds only whole hours by construction: refreshing
 * more often would re-scan log_entry to produce the same rows. Anything the view
 * does not cover yet is read straight from log_entry and merged on top
 * (see {@code LogEntryRepository}), so a refresh that is late, slow or skipped
 * costs query time and never correctness.
 *
 * {@code CONCURRENTLY} keeps readers unblocked for the duration of the rebuild,
 * which on production data takes on the order of a minute.
 */
@Service
public class RequestLogStatsRefreshService {

    private static final Logger log = LoggerFactory.getLogger(RequestLogStatsRefreshService.class);

    /**
     * Arbitrary but fixed: a session-level advisory lock so that two webservice
     * instances (or a manual refresh racing the schedule) serialise instead of
     * piling concurrent rebuilds onto the same table.
     */
    private static final long ADVISORY_LOCK_KEY = 1_022_035L;

    @PersistenceContext
    private EntityManager entityManager;

    @Value("${logos.stats.rollup.refresh-enabled:true}")
    private boolean refreshEnabled;

    /**
     * Five past the hour: the view's newest bucket is the hour that just closed,
     * and the offset leaves room for requests that were still in flight when it
     * did.
     */
    @Scheduled(cron = "${logos.stats.rollup.refresh-cron:0 5 * * * *}")
    public void refreshHourlyStats() {
        if (!refreshEnabled) return;
        refreshNow();
    }

    /**
     * Runs the refresh if no other instance is already running one.
     *
     * @return true if this call performed the refresh, false if it was skipped
     *         because another holder had the lock
     */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public boolean refreshNow() {
        Boolean acquired = (Boolean) entityManager
            .createNativeQuery("SELECT pg_try_advisory_xact_lock(:key)")
            .setParameter("key", ADVISORY_LOCK_KEY)
            .getSingleResult();

        if (!Boolean.TRUE.equals(acquired)) {
            log.debug("stats_rollup: refresh already running elsewhere, skipping");
            return false;
        }

        long startedAt = System.nanoTime();
        try {
            entityManager
                .createNativeQuery("REFRESH MATERIALIZED VIEW CONCURRENTLY log_entry_hourly_stats")
                .executeUpdate();
            long millis = (System.nanoTime() - startedAt) / 1_000_000L;
            log.info("stats_rollup: refreshed log_entry_hourly_stats in {} ms", millis);
            return true;
        } catch (RuntimeException e) {
            // Never fatal: the statistics queries fall back to log_entry for
            // everything the rollup does not cover, so a failed refresh degrades
            // to the pre-rollup query cost rather than to wrong numbers.
            log.warn("stats_rollup: refresh failed, statistics fall back to log_entry: {}", e.getMessage());
            return false;
        }
    }
}
