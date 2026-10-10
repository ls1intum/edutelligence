package de.tum.cit.aet.logos.logoswebservice.operations.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.time.Duration;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

import org.junit.jupiter.api.Test;

class PublicStatsCacheTest {

    private final StatsService statsService = mock(StatsService.class);
    private final AtomicLong now = new AtomicLong();

    {
        when(statsService.publicStats(anyString())).thenAnswer(inv -> new HashMap<>(Map.of("days", inv.getArgument(0))));
    }

    @Test
    void servesEachWindowFromOneComputationUntilTheTtlRunsOut() {
        PublicStatsCache cache = new PublicStatsCache(statsService, Duration.ofMinutes(5), now::get);

        cache.get(null);
        cache.get("30");
        cache.get("7");
        verify(statsService, times(1)).publicStats("30");
        verify(statsService, times(1)).publicStats("7");

        now.addAndGet(Duration.ofMinutes(5).toNanos());
        assertThat(cache.get("30")).containsEntry("days", "30");
        verify(statsService, times(2)).publicStats("30");
    }

    @Test
    void aZeroTtlComputesEveryTime() {
        PublicStatsCache cache = new PublicStatsCache(statsService, Duration.ZERO, now::get);
        cache.get("30");
        cache.get("30");
        verify(statsService, times(2)).publicStats("30");
    }

    @Test
    void rejectsUnknownWindowsWithoutComputing() {
        PublicStatsCache cache = new PublicStatsCache(statsService, Duration.ofMinutes(5), now::get);
        assertThatThrownBy(() -> cache.get("14")).isInstanceOf(IllegalArgumentException.class);
        verifyNoInteractions(statsService);
    }
}
