package de.tum.cit.aet.logos.logoswebservice.operations;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.IntStream;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.LogLevel;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.LogEntryRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.service.RequestLogService;
import de.tum.cit.aet.logos.logoswebservice.operations.service.TeamActivityService;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
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
        ApiKeyRepository apiKeyRepository = mock(ApiKeyRepository.class);

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
        when(apiKeyRepository.existsByTeamIdAndLogAndIsActive(anyInt(), any(LogLevel.class), anyBoolean()))
            .thenReturn(false);

        TeamActivityService service = new TeamActivityService(repository, requestLogService,
            teamRepository, apiKeyRepository, new ObjectMapper(), 10000, 10000, 60);

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
        ApiKeyRepository apiKeyRepository = mock(ApiKeyRepository.class);

        when(repository.findTeamLiveCounts(anyInt(), any(), any())).thenReturn(null);
        when(requestLogService.getLatestRequests(any(), any(), any(), any(), any(), any(), any(),
                                                 anyInt(), anyBoolean()))
            .thenReturn(Map.of("requests", List.of(), "total", 0L, "has_more", false));
        when(teamRepository.findById(anyInt())).thenReturn(Optional.empty());
        when(apiKeyRepository.existsByTeamIdAndLogAndIsActive(anyInt(), any(LogLevel.class), anyBoolean()))
            .thenReturn(false);

        TeamActivityService service = new TeamActivityService(repository, requestLogService,
            teamRepository, apiKeyRepository, new ObjectMapper(), 10000, 10000, 60);

        service.getTeamActivity(2001, 7, null, null, null);
        service.getTeamActivity(2001, 7, null, null, null);

        // The live tier still reads on every poll — that is the point of the
        // view — but the period tier pays once and is served from the cache.
        Mockito.verify(repository, Mockito.times(1)).findTeamKeyUsage(anyInt(), any());
        Mockito.verify(repository, Mockito.times(2)).findTeamLiveCounts(anyInt(), any(), any());
    }
}
