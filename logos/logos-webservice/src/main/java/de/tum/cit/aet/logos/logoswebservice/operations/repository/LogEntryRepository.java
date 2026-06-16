package de.tum.cit.aet.logos.logoswebservice.operations.repository;

import java.sql.Timestamp;
import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.operations.entity.LogEntry;

public interface LogEntryRepository extends JpaRepository<LogEntry, Integer> {

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT le.request_id AS requestId,
               le.timestamp_request AS enqueueTs,
               p.privacy_level::text AS privacyLevel
        FROM log_entry le
        LEFT JOIN providers p ON p.id = le.provider_id
        WHERE le.timestamp_request IS NOT NULL
          AND le.request_id IS NOT NULL
          AND le.timestamp_request >= :startTs
          AND le.timestamp_request <= :endTs
        ORDER BY le.timestamp_request, le.request_id
        LIMIT :limitN
        """, nativeQuery = true)
    List<EnqueueEventProjection> findInRange(
        @Param("startTs") Timestamp startTs,
        @Param("endTs") Timestamp endTs,
        @Param("limitN") int limitN);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT le.request_id AS requestId,
               le.timestamp_request AS enqueueTs,
               p.privacy_level::text AS privacyLevel
        FROM log_entry le
        LEFT JOIN providers p ON p.id = le.provider_id
        WHERE le.timestamp_request IS NOT NULL
          AND le.request_id IS NOT NULL
          AND le.timestamp_request <= :untilTs
        ORDER BY le.timestamp_request, le.request_id
        LIMIT :limitN
        """, nativeQuery = true)
    List<EnqueueEventProjection> findDeltasNoCursor(
        @Param("untilTs") Timestamp untilTs,
        @Param("limitN") int limitN);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT le.request_id AS requestId,
               le.timestamp_request AS enqueueTs,
               p.privacy_level::text AS privacyLevel
        FROM log_entry le
        LEFT JOIN providers p ON p.id = le.provider_id
        WHERE le.timestamp_request IS NOT NULL
          AND le.request_id IS NOT NULL
          AND (le.timestamp_request, le.request_id::text) > (:cursorTs, :cursorId)
          AND le.timestamp_request <= :untilTs
        ORDER BY le.timestamp_request, le.request_id
        LIMIT :limitN
        """, nativeQuery = true)
    List<EnqueueEventProjection> findDeltasWithCursor(
        @Param("cursorTs") Timestamp cursorTs,
        @Param("cursorId") String cursorId,
        @Param("untilTs") Timestamp untilTs,
        @Param("limitN") int limitN);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT le.request_id AS requestId,
               COALESCE(m.name, 'Model ' || le.model_id) AS modelName,
               COALESCE(p.name, 'Provider ' || le.provider_id) AS providerName,
               le.result_status::text AS resultStatus,
               le.timestamp_request AS timestampRequest,
               le.timestamp_forwarding AS timestampForwarding,
               le.timestamp_response AS timestampResponse,
               le.was_cold_start AS wasColdStart,
               le.initial_priority AS initialPriority,
               le.priority_when_scheduled AS priorityWhenScheduled,
               le.queue_depth_at_enqueue AS queueDepthAtEnqueue,
               le.error_message AS errorMessage,
               CASE WHEN le.timestamp_forwarding IS NOT NULL AND le.timestamp_response IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_forwarding))
                    ELSE NULL END AS runSeconds,
               CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_forwarding IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (le.timestamp_forwarding - le.timestamp_request))
                    ELSE NULL END AS queueSeconds,
               CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_response IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_request))
                    ELSE NULL END AS totalSeconds
        FROM log_entry le
        LEFT JOIN models m ON m.id = le.model_id
        LEFT JOIN providers p ON p.id = le.provider_id
        WHERE le.request_id IS NOT NULL
        ORDER BY le.timestamp_request DESC NULLS LAST
        LIMIT 10
        """, nativeQuery = true)
    List<LatestRequestProjection> findLatestRequests();

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT le.request_id AS requestId,
               COALESCE(m.name, 'Model ' || le.model_id) AS modelName,
               COALESCE(p.name, 'Provider ' || le.provider_id) AS providerName,
               le.result_status::text AS resultStatus,
               le.timestamp_request AS enqueueTs,
               le.timestamp_forwarding AS scheduledTs,
               le.timestamp_response AS requestCompleteTs,
               CASE WHEN le.timestamp_request IS NOT NULL AND le.time_at_first_token IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (le.time_at_first_token - le.timestamp_request)) * 1000
                    ELSE NULL END AS ttftMs,
               CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_response IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_request)) * 1000
                    ELSE NULL END AS totalLatencyMs,
               CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_forwarding IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (le.timestamp_forwarding - le.timestamp_request)) * 1000
                    ELSE NULL END AS queueWaitMs,
               CASE WHEN le.timestamp_forwarding IS NOT NULL AND le.timestamp_response IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_forwarding)) * 1000
                    ELSE NULL END AS processingMs,
               le.was_cold_start AS coldStart,
               le.queue_depth_at_arrival AS queueDepthAtArrival,
               le.utilization_at_arrival AS utilizationAtArrival,
               le.queue_depth_at_schedule AS queueDepthAtSchedule,
               le.priority_when_scheduled AS priorityWhenScheduled,
               le.load_duration_ms AS loadDurationMs,
               le.available_vram_mb AS availableVramMb,
               le.azure_rate_remaining_requests AS azureRateRemainingRequests,
               le.azure_rate_remaining_tokens AS azureRateRemainingTokens,
               le.error_message AS errorMessage,
               MAX(CASE WHEN tt.name = 'prompt_tokens'     THEN ut.token_count END) AS promptTokens,
               MAX(CASE WHEN tt.name = 'completion_tokens' THEN ut.token_count END) AS completionTokens,
               MAX(CASE WHEN tt.name = 'total_tokens'      THEN ut.token_count END) AS totalTokens
        FROM log_entry le
        LEFT JOIN models m ON m.id = le.model_id
        LEFT JOIN providers p ON p.id = le.provider_id
        LEFT JOIN usage_tokens ut ON ut.log_entry_id = le.id
        LEFT JOIN token_types tt ON tt.id = ut.type_id
        WHERE (CAST(:apiKeyId AS INTEGER) IS NULL OR le.api_key_id = CAST(:apiKeyId AS INTEGER))
          AND le.request_id IN (:requestIds)
        GROUP BY le.request_id, m.name, le.model_id, p.name, le.provider_id,
                 le.result_status, le.timestamp_request, le.timestamp_forwarding,
                 le.timestamp_response, le.time_at_first_token, le.was_cold_start,
                 le.queue_depth_at_arrival, le.utilization_at_arrival,
                 le.queue_depth_at_schedule, le.priority_when_scheduled,
                 le.load_duration_ms, le.available_vram_mb,
                 le.azure_rate_remaining_requests, le.azure_rate_remaining_tokens,
                 le.error_message
        ORDER BY le.timestamp_request ASC NULLS LAST
        """, nativeQuery = true)
    List<RequestLogProjection> findRequestLogs(
        @Param("apiKeyId") Integer apiKeyId,
        @Param("requestIds") List<String> requestIds);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT COUNT(*) FROM log_entry WHERE request_id IS NOT NULL AND api_key_id = :apiKeyId
        """, nativeQuery = true)
    Long countByApiKeyId(@Param("apiKeyId") int apiKeyId);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT COUNT(*) FROM log_entry WHERE request_id IS NOT NULL
        """, nativeQuery = true)
    Long countAllRequests();

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT le.request_id AS requestId,
               COALESCE(m.name, 'Model ' || le.model_id) AS modelName,
               COALESCE(p.name, 'Provider ' || le.provider_id) AS providerName,
               p.provider_type::text AS providerType,
               le.result_status::text AS resultStatus,
               le.timestamp_request AS enqueueTs,
               le.timestamp_forwarding AS scheduledTs,
               le.timestamp_response AS requestCompleteTs,
               CASE WHEN le.timestamp_forwarding IS NOT NULL AND le.timestamp_response IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_forwarding))
                    ELSE NULL END AS runSeconds,
               CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_forwarding IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (le.timestamp_forwarding - le.timestamp_request))
                    ELSE NULL END AS queueSeconds,
               CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_response IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_request))
                    ELSE NULL END AS totalSeconds,
               le.was_cold_start AS coldStart,
               le.initial_priority AS initialPriority,
               le.priority_when_scheduled AS priorityWhenScheduled,
               le.queue_depth_at_enqueue AS queueDepthAtEnqueue,
               le.error_message AS errorMessage
        FROM log_entry le
        LEFT JOIN models m ON m.id = le.model_id
        LEFT JOIN providers p ON p.id = le.provider_id
        WHERE le.request_id IS NOT NULL
          AND (CAST(:apiKeyId AS INTEGER) IS NULL OR le.api_key_id = CAST(:apiKeyId AS INTEGER))
        ORDER BY le.timestamp_request DESC NULLS LAST
        LIMIT :perPage OFFSET :offset
        """, nativeQuery = true)
    List<PaginatedRequestProjection> findPaginatedRequests(
        @Param("apiKeyId") Integer apiKeyId,
        @Param("perPage") int perPage,
        @Param("offset") int offset);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT le.request_id AS requestId,
               COALESCE(m.name, 'Model ' || le.model_id) AS modelName,
               COALESCE(p.name, 'Provider ' || le.provider_id) AS providerName,
               le.result_status::text AS resultStatus,
               le.timestamp_request AS enqueueTs,
               le.timestamp_forwarding AS scheduledTs,
               le.timestamp_response AS requestCompleteTs,
               CASE WHEN le.timestamp_request IS NOT NULL AND le.time_at_first_token IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (le.time_at_first_token - le.timestamp_request)) * 1000
                    ELSE NULL END AS ttftMs,
               CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_response IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_request)) * 1000
                    ELSE NULL END AS totalLatencyMs,
               CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_forwarding IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (le.timestamp_forwarding - le.timestamp_request)) * 1000
                    ELSE NULL END AS queueWaitMs,
               CASE WHEN le.timestamp_forwarding IS NOT NULL AND le.timestamp_response IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_forwarding)) * 1000
                    ELSE NULL END AS processingMs,
               le.was_cold_start AS coldStart,
               le.queue_depth_at_arrival AS queueDepthAtArrival,
               le.utilization_at_arrival AS utilizationAtArrival,
               le.queue_depth_at_schedule AS queueDepthAtSchedule,
               le.priority_when_scheduled AS priorityWhenScheduled,
               le.load_duration_ms AS loadDurationMs,
               le.available_vram_mb AS availableVramMb,
               le.azure_rate_remaining_requests AS azureRateRemainingRequests,
               le.azure_rate_remaining_tokens AS azureRateRemainingTokens,
               le.error_message AS errorMessage,
               MAX(CASE WHEN tt.name = 'prompt_tokens'     THEN ut.token_count END) AS promptTokens,
               MAX(CASE WHEN tt.name = 'completion_tokens' THEN ut.token_count END) AS completionTokens,
               MAX(CASE WHEN tt.name = 'total_tokens'      THEN ut.token_count END) AS totalTokens
        FROM log_entry le
        LEFT JOIN models m ON m.id = le.model_id
        LEFT JOIN providers p ON p.id = le.provider_id
        LEFT JOIN usage_tokens ut ON ut.log_entry_id = le.id
        LEFT JOIN token_types tt ON tt.id = ut.type_id
        WHERE le.api_key_id IN (SELECT id FROM api_keys WHERE user_id = :userId AND is_active = true)
          AND le.request_id IN (:requestIds)
        GROUP BY le.request_id, m.name, le.model_id, p.name, le.provider_id,
                 le.result_status, le.timestamp_request, le.timestamp_forwarding,
                 le.timestamp_response, le.time_at_first_token, le.was_cold_start,
                 le.queue_depth_at_arrival, le.utilization_at_arrival,
                 le.queue_depth_at_schedule, le.priority_when_scheduled,
                 le.load_duration_ms, le.available_vram_mb,
                 le.azure_rate_remaining_requests, le.azure_rate_remaining_tokens,
                 le.error_message
        ORDER BY le.timestamp_request ASC NULLS LAST
        """, nativeQuery = true)
    List<RequestLogProjection> findRequestLogsByUser(
        @Param("userId") int userId,
        @Param("requestIds") List<String> requestIds);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT COUNT(*) FROM log_entry WHERE request_id IS NOT NULL
          AND api_key_id IN (SELECT id FROM api_keys WHERE user_id = :userId AND is_active = true)
        """, nativeQuery = true)
    Long countByUserId(@Param("userId") int userId);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT le.request_id AS requestId,
               COALESCE(m.name, 'Model ' || le.model_id) AS modelName,
               COALESCE(p.name, 'Provider ' || le.provider_id) AS providerName,
               p.provider_type::text AS providerType,
               le.result_status::text AS resultStatus,
               le.timestamp_request AS enqueueTs,
               le.timestamp_forwarding AS scheduledTs,
               le.timestamp_response AS requestCompleteTs,
               CASE WHEN le.timestamp_forwarding IS NOT NULL AND le.timestamp_response IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_forwarding))
                    ELSE NULL END AS runSeconds,
               CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_forwarding IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (le.timestamp_forwarding - le.timestamp_request))
                    ELSE NULL END AS queueSeconds,
               CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_response IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_request))
                    ELSE NULL END AS totalSeconds,
               le.was_cold_start AS coldStart,
               le.initial_priority AS initialPriority,
               le.priority_when_scheduled AS priorityWhenScheduled,
               le.queue_depth_at_enqueue AS queueDepthAtEnqueue,
               le.error_message AS errorMessage
        FROM log_entry le
        LEFT JOIN models m ON m.id = le.model_id
        LEFT JOIN providers p ON p.id = le.provider_id
        WHERE le.request_id IS NOT NULL
          AND le.api_key_id IN (SELECT id FROM api_keys WHERE user_id = :userId AND is_active = true)
        ORDER BY le.timestamp_request DESC NULLS LAST
        LIMIT :perPage OFFSET :offset
        """, nativeQuery = true)
    List<PaginatedRequestProjection> findPaginatedRequestsByUser(
        @Param("userId") int userId,
        @Param("perPage") int perPage,
        @Param("offset") int offset);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT MAX(COALESCE(timestamp_forwarding, timestamp_request, timestamp_response)) AS lastTs
        FROM log_entry
        WHERE COALESCE(timestamp_forwarding, timestamp_request, timestamp_response) BETWEEN :start AND :end
        """, nativeQuery = true)
    LastEventTsProjection findLastEventTs(
        @Param("start") Timestamp start,
        @Param("end") Timestamp end);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT COUNT(*) AS requests,
               COUNT(*) FILTER (WHERE p.privacy_level != 'LOCAL' AND p.privacy_level IS NOT NULL) AS cloudRequests,
               COUNT(*) FILTER (WHERE p.privacy_level = 'LOCAL' OR p.privacy_level IS NULL) AS localRequests,
               COUNT(*) FILTER (WHERE was_cold_start IS TRUE) AS coldStarts,
               COUNT(*) FILTER (WHERE was_cold_start IS NOT TRUE) AS warmStarts,
               AVG(CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_forwarding IS NOT NULL
                   THEN EXTRACT(EPOCH FROM (le.timestamp_forwarding - le.timestamp_request)) END) AS avgQueueSeconds,
               AVG(CASE WHEN le.timestamp_forwarding IS NOT NULL AND le.timestamp_response IS NOT NULL
                   THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_forwarding)) END) AS avgRunSeconds
        FROM log_entry le
        LEFT JOIN providers p ON p.id = le.provider_id
        WHERE COALESCE(timestamp_forwarding, timestamp_request, timestamp_response) BETWEEN :start AND :end
        """, nativeQuery = true)
    RequestLogTotalsProjection findTotals(
        @Param("start") Timestamp start,
        @Param("end") Timestamp end);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT COALESCE(result_status::text, 'unknown') AS status, COUNT(*) AS cnt
        FROM log_entry
        WHERE COALESCE(timestamp_forwarding, timestamp_request, timestamp_response) BETWEEN :start AND :end
        GROUP BY 1
        """, nativeQuery = true)
    List<StatusCountProjection> findStatusCounts(
        @Param("start") Timestamp start,
        @Param("end") Timestamp end);

    // Model breakdown — a TRUE per-model breakdown, aggregated across ALL providers.
    // A single model can be served by multiple providers; grouping by provider would
    // emit one row per (model, provider) pair, which the stats UI (keyed by model
    // name) renders as duplicated entries for the same model.
    @Transactional(readOnly = true)
    @Query(value = """
        SELECT re.model_id AS modelId,
               COALESCE(m.name, 'Model ' || re.model_id) AS modelName,
               COUNT(*) AS requestCount,
               AVG(CASE WHEN re.timestamp_request IS NOT NULL AND re.timestamp_forwarding IS NOT NULL
                   THEN EXTRACT(EPOCH FROM (re.timestamp_forwarding - re.timestamp_request)) END) AS avgQueueSeconds,
               AVG(CASE WHEN re.timestamp_forwarding IS NOT NULL AND re.timestamp_response IS NOT NULL
                   THEN EXTRACT(EPOCH FROM (re.timestamp_response - re.timestamp_forwarding)) END) AS avgRunSeconds,
               SUM(CASE WHEN re.was_cold_start IS TRUE THEN 1 ELSE 0 END) AS coldStarts,
               SUM(CASE WHEN re.was_cold_start IS NOT TRUE THEN 1 ELSE 0 END) AS warmStarts,
               SUM(CASE WHEN re.result_status IS DISTINCT FROM 'success'
                              OR (re.error_message IS NOT NULL AND re.error_message != '')
                        THEN 1 ELSE 0 END) AS errorCount
        FROM log_entry re
        LEFT JOIN models m ON m.id = re.model_id
        WHERE COALESCE(timestamp_forwarding, timestamp_request, timestamp_response) BETWEEN :start AND :end
        GROUP BY re.model_id, modelName
        ORDER BY requestCount DESC
        """, nativeQuery = true)
    List<ModelBreakdownProjection> findModelBreakdown(
        @Param("start") Timestamp start,
        @Param("end") Timestamp end);

    @Transactional(readOnly = true)
    @Query(value = """
        WITH bucket_series AS (
            SELECT generate_series(
                to_timestamp(FLOOR(EXTRACT(EPOCH FROM CAST(:start AS timestamptz)) / :bucketSec) * :bucketSec),
                to_timestamp(FLOOR(EXTRACT(EPOCH FROM CAST(:end AS timestamptz)) / :bucketSec) * :bucketSec),
                (:bucketSec || ' seconds')::interval
            ) AS bucket_ts
        ),
        agg AS (
            SELECT to_timestamp(FLOOR(EXTRACT(EPOCH FROM COALESCE(re.timestamp_forwarding, re.timestamp_request, re.timestamp_response)) / :bucketSec) * :bucketSec) AS bucket_ts,
                   COUNT(*) AS total,
                   SUM(CASE WHEN p.privacy_level != 'LOCAL' AND p.privacy_level IS NOT NULL THEN 1 ELSE 0 END) AS cloud,
                   SUM(CASE WHEN p.privacy_level = 'LOCAL' OR p.privacy_level IS NULL THEN 1 ELSE 0 END) AS local,
                   AVG(CASE WHEN re.timestamp_forwarding IS NOT NULL AND re.timestamp_response IS NOT NULL
                       THEN EXTRACT(EPOCH FROM (re.timestamp_response - re.timestamp_forwarding)) END) AS avgRunSeconds,
                   AVG(re.available_vram_mb) AS avgVram
            FROM log_entry re
            LEFT JOIN providers p ON p.id = re.provider_id
            WHERE COALESCE(re.timestamp_forwarding, re.timestamp_request, re.timestamp_response) BETWEEN :start AND :end
            GROUP BY 1
        )
        SELECT EXTRACT(EPOCH FROM bs.bucket_ts) AS bucketTs,
               COALESCE(agg.total, 0) AS total,
               COALESCE(agg.cloud, 0) AS cloud,
               COALESCE(agg.local, 0) AS local,
               agg.avgRunSeconds AS avgRunSeconds,
               agg.avgVram AS avgVram
        FROM bucket_series bs
        LEFT JOIN agg ON agg.bucket_ts = bs.bucket_ts
        ORDER BY bs.bucket_ts
        """, nativeQuery = true)
    List<TimeSeriesProjection> findTimeSeries(
        @Param("start") Timestamp start,
        @Param("end") Timestamp end,
        @Param("bucketSec") int bucketSec);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT EXTRACT(EPOCH FROM to_timestamp(FLOOR(EXTRACT(EPOCH FROM COALESCE(re.timestamp_forwarding, re.timestamp_request, re.timestamp_response)) / :bucketSec) * :bucketSec)) AS bucketTs,
               re.model_id AS modelId,
               COALESCE(m.name, 'Model ' || re.model_id) AS modelName,
               COUNT(*) AS count
        FROM log_entry re
        LEFT JOIN models m ON m.id = re.model_id
        WHERE COALESCE(re.timestamp_forwarding, re.timestamp_request, re.timestamp_response) BETWEEN :start AND :end
          AND re.model_id IS NOT NULL
        GROUP BY 1, re.model_id, m.name
        ORDER BY 1, modelName
        """, nativeQuery = true)
    List<ModelTimeSeriesProjection> findModelTimeSeries(
        @Param("start") Timestamp start,
        @Param("end") Timestamp end,
        @Param("bucketSec") int bucketSec);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT AVG(queue_depth_at_enqueue) AS avgEnqueue,
               AVG(queue_depth_at_schedule) AS avgSchedule,
               PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY queue_depth_at_enqueue) AS p95Enqueue,
               PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY queue_depth_at_schedule) AS p95Schedule
        FROM log_entry
        WHERE COALESCE(timestamp_forwarding, timestamp_request, timestamp_response) BETWEEN :start AND :end
          AND (queue_depth_at_enqueue IS NOT NULL OR queue_depth_at_schedule IS NOT NULL)
        """, nativeQuery = true)
    QueueDepthProjection findQueueDepth(
        @Param("start") Timestamp start,
        @Param("end") Timestamp end);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT CASE WHEN was_cold_start IS TRUE THEN 'cold' ELSE 'warm' END AS kind,
               COUNT(*) AS count,
               AVG(CASE WHEN timestamp_forwarding IS NOT NULL AND timestamp_response IS NOT NULL
                   THEN EXTRACT(EPOCH FROM (timestamp_response - timestamp_forwarding)) END) AS avgRunSeconds
        FROM log_entry
        WHERE COALESCE(timestamp_forwarding, timestamp_request, timestamp_response) BETWEEN :start AND :end
        GROUP BY kind
        """, nativeQuery = true)
    List<RuntimeByColdStartProjection> findRuntimeByColdStart(
        @Param("start") Timestamp start,
        @Param("end") Timestamp end);
}
