package de.tum.cit.aet.logos.logoswebservice.common;

import java.time.Clock;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executor;
import java.util.function.Supplier;
import java.util.function.UnaryOperator;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Values served from memory and reloaded in the background, keyed by string.
 *
 * <p>For state that is read on a hot path and whose source is a query too
 * slow to wait for: a read returns the cached value, and once that value is
 * older than {@code refreshAfterMillis} one load per key runs in the
 * background while the expired value keeps answering. Only a key with no
 * value yet, or one older than {@code maxStaleMillis} (the fallback when
 * background loads keep failing), loads on the calling thread; concurrent
 * callers of such a load share it.
 *
 * <p>A change the owner knows about is applied to the cached value at once
 * with {@link #update}. If a load of that key is running, the change is also
 * queued and applied to the loaded value when it is installed, so the load
 * cannot discard it. If the load already saw the change in its source, the
 * change counts twice until the next load, which installs the source value
 * as it is.
 *
 * <p>logos-orchestrator keeps its lane locks the same way
 * ({@code logos/background_refresh.py}).
 */
public final class BackgroundRefreshedCache {

    private static final Logger log = LoggerFactory.getLogger(BackgroundRefreshedCache.class);

    /** Bounded entry count; expired-past-the-stale-limit entries are dropped when it is exceeded. */
    private static final int MAX_ENTRIES = 4096;

    /** Bounded monitors: the same stripe serializes an update against the install of a load. */
    private static final int MONITOR_STRIPES = 64;

    private final String name;
    private final long refreshAfterMillis;
    private final long maxStaleMillis;
    private final Clock clock;
    private final Executor refreshExecutor;

    private final ConcurrentHashMap<String, Entry> entries = new ConcurrentHashMap<>();
    /** Changes applied while a load of the key is in flight, replayed onto the loaded value. */
    private final ConcurrentHashMap<String, List<UnaryOperator<Object>>> pendingChanges = new ConcurrentHashMap<>();
    /** One load per key at a time; concurrent callers share it. */
    private final ConcurrentHashMap<String, CompletableFuture<Entry>> inflight = new ConcurrentHashMap<>();
    private final Object[] monitorStripes = new Object[MONITOR_STRIPES];

    /**
     * @param refreshAfterMillis age after which a value is reloaded in the
     *                           background; 0 or less disables the cache
     *                           (every read loads)
     * @param maxStaleMillis     age after which a read waits for a load
     *                           instead of answering from the old value;
     *                           never less than {@code refreshAfterMillis}
     * @param refreshExecutor    runs the background loads
     */
    public BackgroundRefreshedCache(String name, long refreshAfterMillis, long maxStaleMillis,
                                    Clock clock, Executor refreshExecutor) {
        this.name = name;
        this.refreshAfterMillis = refreshAfterMillis;
        this.maxStaleMillis = Math.max(refreshAfterMillis, maxStaleMillis);
        this.clock = clock;
        this.refreshExecutor = refreshExecutor;
        for (int i = 0; i < MONITOR_STRIPES; i++) {
            monitorStripes[i] = new Object();
        }
    }

    /** A cached value with the time its load finished and the time it started. */
    public record Entry(Object value, long loadedAtMs, long loadStartedAtMs) {
    }

    /** The value for {@code key}; see the class comment for when {@code loader} runs. */
    @SuppressWarnings("unchecked")
    public <T> T get(String key, Supplier<T> loader) {
        if (refreshAfterMillis <= 0) {
            return loader.get();
        }
        long now = clock.millis();
        Entry entry = entries.get(key);
        if (entry != null && now - entry.loadedAtMs() < refreshAfterMillis) {
            return (T) entry.value();
        }
        if (entry != null && now - entry.loadedAtMs() < maxStaleMillis) {
            refreshInBackground(key, loader, now);
            return (T) entry.value();
        }
        Entry loaded = refresh(key, loader, now);
        if (entries.size() > MAX_ENTRIES) {
            long t = clock.millis();
            entries.entrySet().removeIf(e -> t - e.getValue().loadedAtMs() >= maxStaleMillis);
        }
        return (T) loaded.value();
    }

    /**
     * Apply a known change to the cached value of {@code key} at once. The
     * entry keeps its load time, so it is reloaded on the same schedule. A key
     * with no cached value needs nothing: its next load reads the change from
     * the source.
     */
    public void update(String key, UnaryOperator<Object> change) {
        if (refreshAfterMillis <= 0) {
            return;
        }
        synchronized (monitorFor(key)) {
            entries.computeIfPresent(key,
                (k, entry) -> new Entry(change.apply(entry.value()), entry.loadedAtMs(), entry.loadStartedAtMs()));
            if (inflight.containsKey(key)) {
                pendingChanges.computeIfAbsent(key, ignored -> new ArrayList<>()).add(change);
            }
        }
    }

    /** Visible for tests. */
    public Map<String, Entry> view() {
        return entries;
    }

    private <T> void refreshInBackground(String key, Supplier<T> loader, long refreshStartedAtMs) {
        if (inflight.containsKey(key)) {
            return;
        }
        try {
            refreshExecutor.execute(() -> {
                try {
                    refresh(key, loader, refreshStartedAtMs);
                } catch (RuntimeException e) {
                    // The expired value keeps answering; a later read tries
                    // again, and past the stale limit one loads in line.
                    log.warn("Background refresh of {} {} failed: {}", name, key, e.toString());
                }
            });
        } catch (RuntimeException e) {
            log.warn("Could not start a background refresh of {} {}: {}", name, key, e.toString());
        }
    }

    /**
     * Load a fresh value for {@code key}, sharing the work among concurrent
     * callers. Changes queued during the load are applied to the loaded value
     * on install; the previous value is never merged into it.
     */
    Entry refresh(String key, Supplier<?> loader, long refreshStartedAtMs) {
        CompletableFuture<Entry> created = new CompletableFuture<>();
        CompletableFuture<Entry> winner = inflight.computeIfAbsent(key, k -> created);
        if (winner != created) {
            return join(winner);
        }
        Object monitor = monitorFor(key);
        long loadStartedAtMs;
        try {
            synchronized (monitor) {
                Entry latest = entries.get(key);
                long now = clock.millis();
                if (latest != null && now - latest.loadedAtMs() < refreshAfterMillis) {
                    // Another caller installed a fresh value after this one
                    // registered its flight. Drop changes queued against this
                    // flight: update already applied them to the live value,
                    // and replaying them on the next load would count twice.
                    pendingChanges.remove(key);
                    created.complete(latest);
                    inflight.remove(key, created);
                    return latest;
                }
                loadStartedAtMs = clock.millis();
            }

            Object value = loader.get();
            long loadedAt = clock.millis();

            synchronized (monitor) {
                List<UnaryOperator<Object>> pending = pendingChanges.remove(key);
                Entry installed = entries.compute(key, (k, existing) -> {
                    if (existing != null
                            && existing.loadedAtMs() >= refreshStartedAtMs
                            && loadedAt - existing.loadedAtMs() < refreshAfterMillis) {
                        // A newer value landed meanwhile: keep it, plus the changes.
                        return new Entry(applyAll(existing.value(), pending), existing.loadedAtMs(),
                            existing.loadStartedAtMs());
                    }
                    return new Entry(applyAll(value, pending), loadedAt, loadStartedAtMs);
                });
                created.complete(installed);
                inflight.remove(key, created);
                return installed;
            }
        } catch (RuntimeException | Error e) {
            created.completeExceptionally(e);
            throw e;
        } finally {
            inflight.remove(key, created);
        }
    }

    /** Visible for tests: register a load of {@code key} as running without running one. */
    CompletableFuture<Entry> markInflight(String key) {
        CompletableFuture<Entry> planted = new CompletableFuture<>();
        inflight.put(key, planted);
        return planted;
    }

    /** Visible for tests: forget a load registered with {@link #markInflight}. */
    void clearInflight(String key) {
        inflight.remove(key);
    }

    private static Object applyAll(Object value, List<UnaryOperator<Object>> changes) {
        if (changes == null) {
            return value;
        }
        Object result = value;
        for (UnaryOperator<Object> change : changes) {
            result = change.apply(result);
        }
        return result;
    }

    private Object monitorFor(String key) {
        int h = key.hashCode();
        return monitorStripes[(h ^ (h >>> 16)) & (MONITOR_STRIPES - 1)];
    }

    private static Entry join(CompletableFuture<Entry> future) {
        try {
            return future.get();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Interrupted waiting for a cache refresh", e);
        } catch (ExecutionException e) {
            Throwable cause = e.getCause();
            if (cause instanceof RuntimeException re) {
                throw re;
            }
            if (cause instanceof Error err) {
                throw err;
            }
            throw new IllegalStateException("Cache refresh failed", cause);
        }
    }
}
