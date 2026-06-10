package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.sql.Timestamp;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Service;

import de.tum.cit.aet.logos.logoswebservice.operations.repository.LogEntryRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.ModelBreakdownProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.ModelTimeSeriesProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.QueueDepthProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.RequestLogTotalsProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.RuntimeByColdStartProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.StatusCountProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.TimeSeriesProjection;

@Service
public class RequestLogStatsService {

    private static final int[] NICE_BUCKETS = {60, 300, 900, 1800, 3600, 10800, 21600, 43200, 86400};

    private final LogEntryRepository logEntryRepository;

    public RequestLogStatsService(LogEntryRepository logEntryRepository) {
        this.logEntryRepository = logEntryRepository;
    }

    public Map<String, Object> getRequestLogStats(String startDate, String endDate, int targetBuckets) {
        ZonedDateTime now = ZonedDateTime.now(ZoneOffset.UTC);
        ZonedDateTime endDt = endDate != null ? ZonedDateTime.parse(endDate).withZoneSameInstant(ZoneOffset.UTC) : now;
        ZonedDateTime startDt = startDate != null
                ? ZonedDateTime.parse(startDate).withZoneSameInstant(ZoneOffset.UTC)
                : endDt.minusDays(30);

        if (startDt.isAfter(endDt)) {
            throw new IllegalArgumentException("start_date must be before end_date");
        }

        long durationSeconds = Math.max(endDt.toEpochSecond() - startDt.toEpochSecond(), 1);
        int bucketSeconds = chooseBucketSeconds(durationSeconds, Math.max(targetBuckets, 1));

        Timestamp startTs = Timestamp.from(startDt.toInstant());
        Timestamp endTs   = Timestamp.from(endDt.toInstant());

        String lastEventTs = queryLastEventTs(startTs, endTs);
        Map<String, Object> totals = queryTotals(startTs, endTs);
        Map<String, Integer> statusCounts = queryStatusCounts(startTs, endTs);
        List<Map<String, Object>> modelBreakdown = queryModelBreakdown(startTs, endTs);
        List<Map<String, Object>> timeSeries = queryTimeSeries(startTs, endTs, bucketSeconds);
        List<Map<String, Object>> modelTimeSeries = queryModelTimeSeries(startTs, endTs, bucketSeconds);
        Map<String, Object> queueDepth = queryQueueDepth(startTs, endTs);
        List<Map<String, Object>> runtimeByColdStart = queryRuntimeByColdStart(startTs, endTs);

        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("lastEventTs", lastEventTs);
        stats.put("totals", totals);
        stats.put("statusCounts", statusCounts);
        stats.put("modelBreakdown", modelBreakdown);
        stats.put("timeSeries", timeSeries);
        stats.put("modelTimeSeries", modelTimeSeries);
        stats.put("queueDepth", queueDepth);
        stats.put("runtimeByColdStart", runtimeByColdStart);

        Map<String, Object> range = new LinkedHashMap<>();
        range.put("start", startDt.toInstant().toString());
        range.put("end", endDt.toInstant().toString());

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("range", range);
        payload.put("bucketSeconds", bucketSeconds);
        payload.put("stats", stats);
        return payload;
    }

    private String queryLastEventTs(Timestamp start, Timestamp end) {
        var result = logEntryRepository.findLastEventTs(start, end);
        java.time.Instant t = result != null ? result.getLastTs() : null;
        return t != null ? t.toString() : null;
    }

    private Map<String, Object> queryTotals(Timestamp start, Timestamp end) {
        RequestLogTotalsProjection p = logEntryRepository.findTotals(start, end);
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("requests", p.getRequests());
        m.put("cloudRequests", p.getCloudRequests());
        m.put("localRequests", p.getLocalRequests());
        m.put("coldStarts", p.getColdStarts());
        m.put("warmStarts", p.getWarmStarts());
        m.put("avgQueueSeconds", p.getAvgQueueSeconds());
        m.put("avgRunSeconds", p.getAvgRunSeconds());
        return m;
    }

    private Map<String, Integer> queryStatusCounts(Timestamp start, Timestamp end) {
        Map<String, Integer> counts = new LinkedHashMap<>();
        for (StatusCountProjection p : logEntryRepository.findStatusCounts(start, end)) {
            counts.put(p.getStatus().toLowerCase(), p.getCnt());
        }
        return counts;
    }

    private List<Map<String, Object>> queryModelBreakdown(Timestamp start, Timestamp end) {
        return logEntryRepository.findModelBreakdown(start, end).stream()
            .map(p -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("modelId", p.getModelId() != null ? p.getModelId() : -1);
                m.put("modelName", p.getModelName());
                m.put("providerName", p.getProviderName());
                m.put("requestCount", p.getRequestCount());
                m.put("avgQueueSeconds", p.getAvgQueueSeconds());
                m.put("avgRunSeconds", p.getAvgRunSeconds());
                m.put("coldStarts", p.getColdStarts());
                m.put("warmStarts", p.getWarmStarts());
                m.put("errorCount", p.getErrorCount());
                return m;
            })
            .toList();
    }

    private List<Map<String, Object>> queryTimeSeries(Timestamp start, Timestamp end, int bucketSeconds) {
        return logEntryRepository.findTimeSeries(start, end, bucketSeconds).stream()
            .filter(p -> p.getBucketTs() != null)
            .map(p -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("timestamp", (long) (double) p.getBucketTs() * 1000L);
                m.put("label", "");
                m.put("cloud", p.getCloud());
                m.put("local", p.getLocal());
                m.put("total", p.getTotal());
                m.put("avgRunSeconds", p.getAvgRunSeconds());
                m.put("avgVram", p.getAvgVram());
                return m;
            })
            .toList();
    }

    private List<Map<String, Object>> queryModelTimeSeries(Timestamp start, Timestamp end, int bucketSeconds) {
        List<Map<String, Object>> result = new ArrayList<>();
        for (ModelTimeSeriesProjection p : logEntryRepository.findModelTimeSeries(start, end, bucketSeconds)) {
            if (p.getBucketTs() == null) continue;
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("timestamp", (long) (double) p.getBucketTs() * 1000L);
            m.put("modelId", p.getModelId());
            m.put("modelName", p.getModelName());
            m.put("count", p.getCount());
            result.add(m);
        }
        return result;
    }

    private Map<String, Object> queryQueueDepth(Timestamp start, Timestamp end) {
        QueueDepthProjection p = logEntryRepository.findQueueDepth(start, end);
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("avgEnqueueDepth", p != null ? p.getAvgEnqueue() : null);
        m.put("avgScheduleDepth", p != null ? p.getAvgSchedule() : null);
        m.put("p95EnqueueDepth", p != null ? p.getP95Enqueue() : null);
        m.put("p95ScheduleDepth", p != null ? p.getP95Schedule() : null);
        return m;
    }

    private List<Map<String, Object>> queryRuntimeByColdStart(Timestamp start, Timestamp end) {
        return logEntryRepository.findRuntimeByColdStart(start, end).stream()
            .map(p -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("type", p.getKind());
                m.put("avgRunSeconds", p.getAvgRunSeconds());
                m.put("count", p.getCount());
                return m;
            })
            .toList();
    }

    static int chooseBucketSeconds(long durationSeconds, int targetBuckets) {
        double rawBucket = Math.max((double) durationSeconds / targetBuckets, 60);
        int best = NICE_BUCKETS[0];
        double bestDiff = Math.abs(rawBucket - best);
        for (int c : NICE_BUCKETS) {
            double diff = Math.abs(rawBucket - c);
            if (diff < bestDiff) { best = c; bestDiff = diff; }
        }
        return best;
    }
}
