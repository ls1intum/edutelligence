package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.time.Duration;
import java.util.Collections;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.LongSupplier;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * Holds the public stats per window for a short while.
 *
 * <p>The page is the one part of the platform anyone can load, and every
 * figure on it comes from a pass over all successful requests — about a second
 * of database time on production. Nobody needs those figures to the second, so
 * each window is computed at most once per {@code logos.public-stats.cache-ttl}
 * (default five minutes) per instance; callers that miss at the same time wait
 * for the one computation instead of starting their own. A TTL of zero turns
 * the cache off.
 */
@Service
public class PublicStatsCache {

    private record Entry(long computedAtNanos, Map<String, Object> stats) {
    }

    private final StatsService statsService;
    private final long ttlNanos;
    private final LongSupplier nanoClock;
    private final Map<String, Entry> entries = new ConcurrentHashMap<>();
    private final Map<String, Object> locks = new ConcurrentHashMap<>();

    @Autowired
    public PublicStatsCache(StatsService statsService,
                            @Value("${logos.public-stats.cache-ttl:PT5M}") Duration ttl) {
        this(statsService, ttl, System::nanoTime);
    }

    PublicStatsCache(StatsService statsService, Duration ttl, LongSupplier nanoClock) {
        this.statsService = statsService;
        this.ttlNanos = ttl.toNanos();
        this.nanoClock = nanoClock;
    }

    /** The stats for {@code days}; rejects unknown windows like {@link StatsService#publicStats}. */
    public Map<String, Object> get(String days) {
        String window = StatsService.normalizePublicStatsDays(days);
        if (ttlNanos <= 0) {
            return statsService.publicStats(window);
        }
        Entry entry = entries.get(window);
        if (isFresh(entry)) {
            return entry.stats();
        }
        synchronized (locks.computeIfAbsent(window, k -> new Object())) {
            entry = entries.get(window);
            if (isFresh(entry)) {
                return entry.stats();
            }
            Map<String, Object> stats = Collections.unmodifiableMap(statsService.publicStats(window));
            entries.put(window, new Entry(nanoClock.getAsLong(), stats));
            return stats;
        }
    }

    private boolean isFresh(Entry entry) {
        return entry != null && nanoClock.getAsLong() - entry.computedAtNanos() < ttlNanos;
    }
}
