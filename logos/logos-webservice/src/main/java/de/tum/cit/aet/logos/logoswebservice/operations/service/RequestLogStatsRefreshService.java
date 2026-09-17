package de.tum.cit.aet.logos.logoswebservice.operations.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

/**
 * Keeps {@code log_entry_hourly_stats} — the rollup behind the statistics page —
 * current.
 *
 * Hourly, because the view holds only whole hours by construction: refreshing
 * more often would re-scan log_entry to produce the same rows. Anything the view
 * does not cover is read straight from log_entry and merged on top
 * (see {@code LogEntryRepository}), so a refresh that is late, slow or skipped
 * costs query time and never correctness.
 *
 * The refresh itself lives in {@link RequestLogStatsRollupRefresher} and is
 * reached through the injected bean rather than a method on this class, so that
 * Spring's transaction proxy actually runs — see that class for why the advisory
 * lock depends on it.
 */
@Service
public class RequestLogStatsRefreshService {

    private final RequestLogStatsRollupRefresher refresher;

    @Value("${logos.stats.rollup.refresh-enabled:true}")
    private boolean refreshEnabled;

    public RequestLogStatsRefreshService(RequestLogStatsRollupRefresher refresher) {
        this.refresher = refresher;
    }

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
     */
    public boolean refreshNow() {
        return refresher.refresh();
    }
}
