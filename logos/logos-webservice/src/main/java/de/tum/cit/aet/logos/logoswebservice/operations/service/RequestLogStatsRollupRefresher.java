package de.tum.cit.aet.logos.logoswebservice.operations.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;

/**
 * The transactional half of the rollup refresh.
 *
 * Its own bean, and not a method on {@link RequestLogStatsRefreshService}, for a
 * reason that is easy to get wrong: Spring applies {@code @Transactional} through
 * a proxy, so a scheduled method calling a transactional method on {@code this}
 * gets no transaction at all. The advisory lock below is transaction-scoped —
 * without a transaction Postgres commits the SELECT that takes it immediately and
 * releases it again, so the lock would guard nothing and two instances could
 * rebuild the view at once. Going through an injected bean is what makes the
 * proxy, and therefore the transaction and the lock, real.
 */
@Component
public class RequestLogStatsRollupRefresher {

    private static final Logger log = LoggerFactory.getLogger(RequestLogStatsRollupRefresher.class);

    /**
     * Arbitrary but fixed: the advisory lock key that serialises refreshes across
     * webservice instances.
     */
    private static final long ADVISORY_LOCK_KEY = 1_022_035L;

    @PersistenceContext
    private EntityManager entityManager;

    /**
     * Rebuilds {@code log_entry_hourly_stats} unless another holder is already
     * doing it.
     *
     * {@code REQUIRES_NEW} so the lock and the refresh always share one
     * transaction of their own, whatever the caller was doing.
     *
     * @return true if this call performed the refresh, false if it was skipped
     *         because another holder had the lock or the refresh failed
     */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public boolean refresh() {
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
            // Never fatal: the statistics queries read log_entry for everything
            // the rollup does not cover, so a failed refresh degrades to the
            // pre-rollup query cost rather than to wrong numbers.
            log.warn("stats_rollup: refresh failed, statistics fall back to log_entry: {}", e.getMessage());
            return false;
        }
    }
}
