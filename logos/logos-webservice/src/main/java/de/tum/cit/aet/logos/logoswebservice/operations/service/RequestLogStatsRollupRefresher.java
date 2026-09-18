package de.tum.cit.aet.logos.logoswebservice.operations.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;

/**
 * The transactional half of the rollup pass.
 *
 * Its own bean, and not a method on {@link RequestLogStatsRefreshService}, for a
 * reason that is easy to get wrong: Spring applies {@code @Transactional} through
 * a proxy, so a scheduled method calling a transactional method on {@code this}
 * gets no transaction at all. The advisory lock below is transaction-scoped —
 * without a transaction Postgres commits the SELECT that takes it immediately and
 * releases it again, so the lock would guard nothing and two instances could run
 * a pass at once, each recomputing the same hours from a different cutoff.
 * Going through an injected bean is what makes the proxy, and therefore the
 * transaction and the lock, real.
 */
@Component
public class RequestLogStatsRollupRefresher {

    private static final Logger log = LoggerFactory.getLogger(RequestLogStatsRollupRefresher.class);

    /**
     * Arbitrary but fixed: the advisory lock key that serialises passes across
     * webservice instances.
     */
    private static final long ADVISORY_LOCK_KEY = 1_022_035L;

    @PersistenceContext
    private EntityManager entityManager;

    /**
     * How far behind now() a pass stops reading, so that a write transaction
     * which started before the cutoff but commits after it is not skipped. Must
     * exceed the longest write transaction on log_entry; zero is only safe where
     * nothing else is writing, which is what the tests arrange.
     */
    @Value("${logos.stats.rollup.write-lag:1 minute}")
    private String writeLag;

    /**
     * Brings {@code log_entry_hourly_stats} up to date, unless another holder is
     * already doing it.
     *
     * The work is a single call to {@code logos_stats_rollup_pass()}, which
     * recomputes only the hours whose rows changed since the previous pass and
     * then advances the state row. Keeping the whole thing in one statement is
     * deliberate: the state row must only move if the hours it accounts for were
     * rebuilt in the same transaction, or a crash between the two would leave
     * the rollup claiming to cover hours it never recomputed.
     *
     * {@code REQUIRES_NEW} so the lock and the pass always share one transaction
     * of their own, whatever the caller was doing.
     *
     * @return true if this call ran a pass, false if it was skipped because
     *         another holder had the lock, or because the pass failed
     */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public boolean refresh() {
        Boolean acquired = (Boolean) entityManager
            .createNativeQuery("SELECT pg_try_advisory_xact_lock(:key)")
            .setParameter("key", ADVISORY_LOCK_KEY)
            .getSingleResult();

        if (!Boolean.TRUE.equals(acquired)) {
            log.debug("stats_rollup: a pass is already running elsewhere, skipping");
            return false;
        }

        long startedAt = System.nanoTime();
        try {
            Object[] result = (Object[]) entityManager
                .createNativeQuery(
                    "SELECT hours_rebuilt, rows_written FROM logos_stats_rollup_pass(CAST(:lag AS interval))")
                .setParameter("lag", writeLag)
                .getSingleResult();
            long millis = (System.nanoTime() - startedAt) / 1_000_000L;
            log.debug("stats_rollup: rebuilt {} hour(s), {} row(s), in {} ms",
                      result[0], result[1], millis);
            return true;
        } catch (RuntimeException e) {
            // Never fatal. A pass that does not run leaves the state row where it
            // was, so the next one picks up the same changes; and once the state
            // row falls behind the reader's freshness guard, the aggregates stop
            // using the rollup altogether and read log_entry. A broken pass makes
            // the page slow, not wrong.
            log.warn("stats_rollup: pass failed, statistics fall back to log_entry: {}", e.getMessage());
            return false;
        }
    }
}
