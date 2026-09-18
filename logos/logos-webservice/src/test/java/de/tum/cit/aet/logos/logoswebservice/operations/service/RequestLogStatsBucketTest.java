package de.tum.cit.aet.logos.logoswebservice.operations.service;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

/**
 * Bucket sizing for the request-volume chart.
 *
 * A ~30-day window must land on daily bars; a calendar day still gets the
 * five-minute buckets the page already advertised.
 */
class RequestLogStatsBucketTest {

    @Test
    void thirtyDayWindowUsesDailyBuckets() {
        assertThat(RequestLogStatsService.chooseBucketSeconds(30L * 86_400, 96))
            .isEqualTo(86_400);
        assertThat(RequestLogStatsService.chooseBucketSeconds(30L * 86_400, 30))
            .isEqualTo(86_400);
    }

    @Test
    void oneDayWindowUsesFiveMinuteBuckets() {
        // Matches the UI's calendar-day target (~288) so daily tooltips read
        // as five-minute ranges like "04:30 – 04:35".
        assertThat(RequestLogStatsService.chooseBucketSeconds(86_400, 288))
            .isEqualTo(300);
    }
}
