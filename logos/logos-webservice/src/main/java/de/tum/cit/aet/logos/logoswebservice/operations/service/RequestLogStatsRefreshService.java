package de.tum.cit.aet.logos.logoswebservice.operations.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

/**
 * Keeps {@code log_entry_hourly_stats} — the rollup behind the statistics page —
 * current.
 *
 * Every minute, because a pass costs what changed rather than what exists: it
 * recomputes only the hours whose rows moved since the previous one, which is
 * normally the hour that just closed plus whatever late cost settlement touched.
 * That cadence is also the freshness the page gets — a request that finishes, or
 * a cost that settles days later, is in the aggregates within about a minute.
 *
 * Nothing here is load-bearing for correctness. The reader's freshness guard
 * stops trusting the rollup once no pass has completed recently, and every
 * aggregate falls back to log_entry; a refresher that dies makes the page slow,
 * not wrong. The pass itself lives in {@link RequestLogStatsRollupRefresher} and
 * is reached through the injected bean rather than a method on this class, so
 * that Spring's transaction proxy actually runs — see that class for why the
 * advisory lock depends on it.
 */
@Service
public class RequestLogStatsRefreshService {

    private final RequestLogStatsRollupRefresher refresher;

    @Value("${logos.stats.rollup.refresh-enabled:true}")
    private boolean refreshEnabled;

    public RequestLogStatsRefreshService(RequestLogStatsRollupRefresher refresher) {
        this.refresher = refresher;
    }

    @Scheduled(cron = "${logos.stats.rollup.refresh-cron:0 * * * * *}")
    public void refreshHourlyStats() {
        if (!refreshEnabled) return;
        refreshNow();
    }

    /**
     * Runs a pass if no other instance is already running one.
     *
     * @return true if this call ran a pass, false if it was skipped
     */
    public boolean refreshNow() {
        return refresher.refresh();
    }
}
