package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.sql.Timestamp;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Service;

import de.tum.cit.aet.logos.logoswebservice.operations.repository.PublicStatsRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.PublicStatsTimeSeriesProjection;

/**
 * The aggregates behind the public statistics page.
 *
 * <p>Success-only by design: the page exists to show that the platform works,
 * so it counts finished, successful requests of the teams that opted in —
 * errors, timeouts, and the in-flight rows in between stay out of every
 * number on it. That is the opposite of the statistics page's
 * {@code errorsOnly} narrowing, which is why the page gets its own queries
 * instead of a flag on the shared ones (see {@link PublicStatsRepository}).
 *
 * <p>Unauthenticated on purpose, which is also why the window is capped: an
 * anonymous caller must not be able to point the page at an unbounded slice of
 * {@code log_entry}. The default is the same 30 days the statistics page
 * defaults to, and anything older than {@link #MAX_WINDOW_DAYS} before the
 * range end is refused with a 400 rather than quietly truncated.
 */
@Service
public class PublicStatsService {

    static final int DEFAULT_WINDOW_DAYS = 30;
    static final int MAX_WINDOW_DAYS = 90;
    private static final long DAY_SECONDS = 86_400;

    private final PublicStatsRepository publicStatsRepository;

    public PublicStatsService(PublicStatsRepository publicStatsRepository) {
        this.publicStatsRepository = publicStatsRepository;
    }

    public Map<String, Object> getPublicStats(String startDate, String endDate) {
        ZonedDateTime now = ZonedDateTime.now(ZoneOffset.UTC);
        ZonedDateTime endDt = endDate != null ? parseParameter(endDate, "end_date") : now;
        ZonedDateTime startDt = startDate != null
                ? parseParameter(startDate, "start_date")
                : endDt.minusDays(DEFAULT_WINDOW_DAYS);

        if (startDt.isAfter(endDt)) {
            throw new IllegalArgumentException("start_date must be before end_date");
        }
        long windowDays = endDt.toEpochSecond() - startDt.toEpochSecond();
        if (windowDays > (long) MAX_WINDOW_DAYS * DAY_SECONDS) {
            throw new IllegalArgumentException(
                "the public statistics window is capped at " + MAX_WINDOW_DAYS + " days");
        }

        Timestamp startTs = Timestamp.from(startDt.toInstant());
        Timestamp endTs   = Timestamp.from(endDt.toInstant());

        var totals = publicStatsRepository.findTotals(startTs, endTs);
        List<Map<String, Object>> models = publicStatsRepository.findModelBreakdown(startTs, endTs).stream()
            .map(p -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("modelId", p.getModelId());
                m.put("modelName", p.getModelName());
                m.put("requestCount", p.getRequestCount());
                return m;
            })
            .toList();

        Map<String, Object> payload = new LinkedHashMap<>();
        Map<String, Object> range = new LinkedHashMap<>();
        range.put("start", startDt.toInstant().toString());
        range.put("end", endDt.toInstant().toString());
        payload.put("range", range);
        Map<String, Object> totalsMap = new LinkedHashMap<>();
        totalsMap.put("requests", totals.getRequests() != null ? totals.getRequests() : 0L);
        totalsMap.put("totalTokens", totals.getTotalTokens() != null ? totals.getTotalTokens() : 0L);
        payload.put("totals", totalsMap);
        payload.put("models", models);
        payload.put("timeSeries", fillDailyBuckets(startDt, endDt, publicStatsRepository.findTimeSeries(startTs, endTs)));
        return payload;
    }

    /**
     * A date the caller could not mean must read as the caller's mistake, not
     * the platform's: DateTimeParseException is not an IllegalArgumentException,
     * so without this translation a malformed parameter would slip past the
     * controller's 400 handling and surface as a server error.
     */
    private static ZonedDateTime parseParameter(String value, String name) {
        try {
            return ZonedDateTime.parse(value).withZoneSameInstant(ZoneOffset.UTC);
        } catch (DateTimeParseException e) {
            throw new IllegalArgumentException(
                name + " must be an ISO-8601 date-time, e.g. 2026-02-01T00:00:00Z");
        }
    }

    /**
     * One entry per day of the window, gaps included. The query returns only
     * the days that carried a successful request; a chart with holes in it
     * would read as missing data rather than as a quiet day.
     */
    private static List<Map<String, Object>> fillDailyBuckets(
            ZonedDateTime startDt, ZonedDateTime endDt,
            List<PublicStatsTimeSeriesProjection> rows) {
        Map<Long, Long> byDay = new LinkedHashMap<>();
        for (PublicStatsTimeSeriesProjection p : rows) {
            if (p.getBucketTs() == null) continue;
            byDay.put(Math.round(p.getBucketTs()), p.getRequestCount());
        }
        List<Map<String, Object>> series = new ArrayList<>();
        for (long day = startDt.toEpochSecond() / DAY_SECONDS; day <= endDt.toEpochSecond() / DAY_SECONDS; day++) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("timestamp", day * DAY_SECONDS * 1000L);
            m.put("requests", byDay.getOrDefault(day * DAY_SECONDS, 0L));
            series.add(m);
        }
        return series;
    }
}
