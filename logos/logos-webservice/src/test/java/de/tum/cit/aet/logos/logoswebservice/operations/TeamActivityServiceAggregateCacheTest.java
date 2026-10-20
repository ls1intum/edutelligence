package de.tum.cit.aet.logos.logoswebservice.operations;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.IntStream;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.LogEntryRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.service.RequestLogService;
import de.tum.cit.aet.logos.logoswebservice.operations.service.TeamActivityService;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * The period tier of the activity view, under several tabs at once.
 *
 * Plain unit test on the service and mocked repositories: the point under
 * test is the single-flight refresh, which is a property of the service
 * itself, and Testcontainers would only add minutes to watch it.
 */
class TeamActivityServiceAggregateCacheTest {

    @Test
    void pollsThatHitTheCacheAtTheSameMomentLoadTheAggregatesOnce() throws Exception {
        LogEntryRepository repository = mock(LogEntryRepository.class);
        RequestLogService requestLogService = mock(RequestLogService.class);
        TeamRepository teamRepository = mock(TeamRepository.class);

        // The key-usage aggregate is the expensive query the cache exists to
        // amortize: count how often it runs, and hold the load open briefly
        // so the other polls arrive while the first one is still in it.
        AtomicInteger keyUsageLoads = new AtomicInteger();
        when(repository.findTeamKeyUsage(anyInt(), any()))
            .thenAnswer(invocation -> {
                keyUsageLoads.incrementAndGet();
                Thread.sleep(50);
                return List.of();
            });
        when(repository.findTeamLiveCounts(anyInt(), any(), any())).thenReturn(null);
        when(repository.findRequestersWithTraffic(any(), any(), any(), any(), anyBoolean()))
            .thenReturn(List.of());
        when(repository.findMostAskedQuestions(any(), any(), any(), anyInt(), anyInt()))
            .thenReturn(List.of());
        when(requestLogService.getLatestRequests(any(), any(), any(), any(), any(), any(), any(),
                                                 anyInt(), anyBoolean()))
            .thenReturn(Map.of("requests", List.of(), "total", 0L, "has_more", false));
        when(teamRepository.findById(anyInt())).thenReturn(Optional.empty());
        when(repository.existsFullPrivacyInWindow(anyInt(), any(), any())).thenReturn(false);

        TeamActivityService service = new TeamActivityService(repository, requestLogService,
            teamRepository, new ObjectMapper(), 10000, 10000, 60);

        // Eight tabs polling one (team, window) the moment its aggregates are
        // not cached yet: they must funnel through one load, and they must
        // all read the same result.
        int polls = 8;
        ExecutorService pool = Executors.newFixedThreadPool(polls);
        try {
            List<Future<Map<String, Object>>> results = IntStream.range(0, polls)
                .mapToObj(i -> pool.submit(() -> service.getTeamActivity(2001, 7, null, null, null)))
                .toList();
            for (Future<Map<String, Object>> result : results) {
                assertNotNull(result.get(30, TimeUnit.SECONDS));
            }
        } finally {
            pool.shutdownNow();
        }

        assertEquals(1, keyUsageLoads.get(),
            "the aggregates of one (team, window) may run once per expiry, not once per poll");
    }

    @Test
    void aFreshEntryIsReadWithoutTouchingTheRepositoriesAgain() {
        LogEntryRepository repository = mock(LogEntryRepository.class);
        RequestLogService requestLogService = mock(RequestLogService.class);
        TeamRepository teamRepository = mock(TeamRepository.class);

        when(repository.findTeamLiveCounts(anyInt(), any(), any())).thenReturn(null);
        when(requestLogService.getLatestRequests(any(), any(), any(), any(), any(), any(), any(),
                                                 anyInt(), anyBoolean()))
            .thenReturn(Map.of("requests", List.of(), "total", 0L, "has_more", false));
        when(teamRepository.findById(anyInt())).thenReturn(Optional.empty());
        when(repository.existsFullPrivacyInWindow(anyInt(), any(), any())).thenReturn(false);

        TeamActivityService service = new TeamActivityService(repository, requestLogService,
            teamRepository, new ObjectMapper(), 10000, 10000, 60);

        service.getTeamActivity(2001, 7, null, null, null);
        service.getTeamActivity(2001, 7, null, null, null);

        // The live tier still reads on every poll — that is the point of the
        // view — but the period tier pays once and is served from the cache.
        Mockito.verify(repository, Mockito.times(1)).findTeamKeyUsage(anyInt(), any());
        Mockito.verify(repository, Mockito.times(2)).findTeamLiveCounts(anyInt(), any(), any());
    }

    /** The team whose refresh holds its lock while the eviction runs. */
    private static final int RACED_TEAM = 1050;
    /** A team the raced team has never met: its load is what triggers the sweep. */
    private static final int SWEEPER_TEAM = 1150;

    @Test
    void anEvictionMidRefreshCannotSplitTheSingleFlightOfOneKey() throws Exception {
        // The race an eviction runs against a refresh: while the first poll
        // of an expired key holds its lock inside the load, an unrelated
        // load can push the cache past its size limit and sweep the expired
        // entries — including this key's — and with them, a lock that is not
        // aware of who holds it. The next poll of the key would then take a
        // fresh lock and start a second, concurrent load of the same
        // aggregates. The lock must stay put for as long as anyone holds it.
        LogEntryRepository repository = mock(LogEntryRepository.class);
        RequestLogService requestLogService = mock(RequestLogService.class);
        TeamRepository teamRepository = mock(TeamRepository.class);

        AtomicInteger racedLoads = new AtomicInteger();
        CountDownLatch firstLoadHolding = new CountDownLatch(1);
        CountDownLatch releaseFirstLoad = new CountDownLatch(1);
        CountDownLatch secondLoadStarted = new CountDownLatch(1);
        CountDownLatch releaseSecondLoad = new CountDownLatch(1);
        when(repository.findTeamKeyUsage(anyInt(), any())).thenAnswer(invocation -> {
            int teamId = invocation.getArgument(0);
            if (teamId == RACED_TEAM) {
                if (racedLoads.incrementAndGet() == 1) {
                    firstLoadHolding.countDown();
                    releaseFirstLoad.await(30, TimeUnit.SECONDS);
                } else {
                    // A second load of the same key: the race the test is
                    // here to catch. Hold it open so the test can name it.
                    secondLoadStarted.countDown();
                    releaseSecondLoad.await(30, TimeUnit.SECONDS);
                }
            }
            return List.of();
        });
        when(repository.findTeamLiveCounts(anyInt(), any(), any())).thenReturn(null);
        when(repository.findRequestersWithTraffic(any(), any(), any(), any(), anyBoolean()))
            .thenReturn(List.of());
        when(repository.findMostAskedQuestions(any(), any(), any(), anyInt(), anyInt()))
            .thenReturn(List.of());
        when(requestLogService.getLatestRequests(any(), any(), any(), any(), any(), any(), any(),
                                                 anyInt(), anyBoolean()))
            .thenReturn(Map.of("requests", List.of(), "total", 0L, "has_more", false));
        when(teamRepository.findById(anyInt())).thenReturn(Optional.empty());
        when(repository.existsFullPrivacyInWindow(anyInt(), any(), any())).thenReturn(false);

        // A one-second TTL: long enough for the test's own loads to stay
        // fresh, short enough that a sleep ages out the filled cache.
        TeamActivityService service = new TeamActivityService(repository, requestLogService,
            teamRepository, new ObjectMapper(), 10000, 10000, 1);

        ExecutorService pool = Executors.newFixedThreadPool(2);
        try {
            // Push the cache past its sweep threshold so the next load runs
            // it — 134 distinct (team, window) entries. The raced team is
            // deliberately not among them: its entry and lock must come into
            // being through the first poll below, not the fill.
            for (int teamId = 1000; teamId <= 1134; teamId++) {
                if (teamId == RACED_TEAM) {
                    continue;
                }
                service.getTeamActivity(teamId, 7, null, null, null);
            }
            Thread.sleep(1500);

            // One poll of the raced key is now inside its load, holding the
            // key's lock ...
            Future<?> first = pool.submit(() -> service.getTeamActivity(RACED_TEAM, 7, null, null, null));
            assertTrue(firstLoadHolding.await(30, TimeUnit.SECONDS));

            // ... while an unrelated load sweeps: every filled entry is
            // expired, and so — with a lock that is not holder-aware — is
            // the raced key's monitor.
            service.getTeamActivity(SWEEPER_TEAM, 7, null, null, null);

            // A further poll of the raced key. It must wait for the first
            // poll's result, not start a second load of the same aggregates.
            Future<?> second = pool.submit(() -> service.getTeamActivity(RACED_TEAM, 7, null, null, null));
            Thread.sleep(300);
            releaseFirstLoad.countDown();
            first.get(30, TimeUnit.SECONDS);

            boolean secondCompleted;
            try {
                second.get(10, TimeUnit.SECONDS);
                secondCompleted = true;
            } catch (TimeoutException e) {
                // The second poll is still inside a load of its own: the
                // eviction split the single-flight.
                secondCompleted = false;
            }
            assertTrue(secondCompleted,
                "the waiting poll must read the first load's result, not run a second load");
            assertEquals(1, secondLoadStarted.getCount(),
                "a second load of the same key started while the first still held its lock");
            assertEquals(1, racedLoads.get(),
                "one key's aggregates load once per expiry, even when an eviction runs mid-refresh");
        } finally {
            releaseSecondLoad.countDown();
            pool.shutdownNow();
        }
    }
}
