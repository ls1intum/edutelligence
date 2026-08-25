package de.tum.cit.aet.logos.logoswebservice.operations.repository;

import java.sql.Timestamp;
import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.operations.entity.LogEntry;

/**
 * Queries behind the statistics page.
 *
 * Every aggregate here takes a nullable {@code userId} / {@code teamId} pair and
 * narrows to it when set, so one query serves both the whole platform and one
 * team's slice of it. The predicate is spelled
 * {@code (CAST(:teamId AS INTEGER) IS NULL OR le.team_id = CAST(:teamId AS INTEGER))}
 * in every one of them: the cast is what tells Postgres the type of a parameter
 * it only ever sees as NULL, and repeating it beats a second copy of each query
 * that could drift from the filtered one.
 *
 * The pair has to reach every aggregate the page draws, not just the request
 * feed. A filter that narrows the list under the charts while the charts keep
 * showing platform-wide totals reads as a bug, because the two disagree about
 * what is on screen.
 */
public interface LogEntryRepository extends JpaRepository<LogEntry, Integer> {

    /**
     * Teams that actually sent something in the range, with how much.
     *
     * The filter dropdowns were built from the platform's user and team
     * inventory, which is a different list: it includes everyone who has never
     * made a request, and every one of those entries is guaranteed to select
     * nothing. Offering only what the range holds is both shorter and honest
     * about what picking it will do.
     */
    @Transactional(readOnly = true)
    @Query(value = """
        SELECT le.team_id AS id,
               COALESCE(t.name, 'Team ' || le.team_id) AS label,
               COUNT(*) AS requestCount
        FROM log_entry le
        LEFT JOIN teams t ON t.id = le.team_id
        WHERE COALESCE(le.timestamp_forwarding, le.timestamp_request, le.timestamp_response) BETWEEN :start AND :end
          AND le.team_id IS NOT NULL
        GROUP BY le.team_id, t.name
        ORDER BY requestCount DESC
        """, nativeQuery = true)
    List<ScopeOptionProjection> findTeamsWithTraffic(
        @Param("start") Timestamp start,
        @Param("end") Timestamp end);

    /**
     * Requesters that actually sent something in the range, optionally only
     * within one team.
     *
     * Scoped by team but deliberately never by user: this list *is* the user
     * picker, so narrowing it by the current selection would leave it holding
     * only the entry already chosen and no way back to the others.
     */
    @Transactional(readOnly = true)
    @Query(value = """
        SELECT le.user_id AS id,
               COALESCE(
                   NULLIF(TRIM(COALESCE(u.prename, '') || ' ' || COALESCE(u.name, '')), ''),
                   u.username,
                   'User ' || le.user_id
               ) AS label,
               COUNT(*) AS requestCount
        FROM log_entry le
        LEFT JOIN users u ON u.id = le.user_id
        WHERE COALESCE(le.timestamp_forwarding, le.timestamp_request, le.timestamp_response) BETWEEN :start AND :end
          AND le.user_id IS NOT NULL
          AND (CAST(:teamId AS INTEGER) IS NULL OR le.team_id = CAST(:teamId AS INTEGER))
        GROUP BY le.user_id, u.prename, u.name, u.username
        ORDER BY requestCount DESC
        """, nativeQuery = true)
    List<ScopeOptionProjection> findRequestersWithTraffic(
        @Param("start") Timestamp start,
        @Param("end") Timestamp end,
        @Param("teamId") Integer teamId);

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
          AND (CAST(:userId AS INTEGER) IS NULL OR le.user_id = CAST(:userId AS INTEGER))
          AND (CAST(:teamId AS INTEGER) IS NULL OR le.team_id = CAST(:teamId AS INTEGER))
        ORDER BY le.timestamp_request, le.request_id
        LIMIT :limitN
        """, nativeQuery = true)
    List<EnqueueEventProjection> findInRange(
        @Param("startTs") Timestamp startTs,
        @Param("endTs") Timestamp endTs,
        @Param("userId") Integer userId,
        @Param("teamId") Integer teamId,
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
          AND (CAST(:userId AS INTEGER) IS NULL OR le.user_id = CAST(:userId AS INTEGER))
          AND (CAST(:teamId AS INTEGER) IS NULL OR le.team_id = CAST(:teamId AS INTEGER))
        ORDER BY le.timestamp_request, le.request_id
        LIMIT :limitN
        """, nativeQuery = true)
    List<EnqueueEventProjection> findDeltasNoCursor(
        @Param("untilTs") Timestamp untilTs,
        @Param("userId") Integer userId,
        @Param("teamId") Integer teamId,
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
          AND (CAST(:userId AS INTEGER) IS NULL OR le.user_id = CAST(:userId AS INTEGER))
          AND (CAST(:teamId AS INTEGER) IS NULL OR le.team_id = CAST(:teamId AS INTEGER))
        ORDER BY le.timestamp_request, le.request_id
        LIMIT :limitN
        """, nativeQuery = true)
    List<EnqueueEventProjection> findDeltasWithCursor(
        @Param("cursorTs") Timestamp cursorTs,
        @Param("cursorId") String cursorId,
        @Param("untilTs") Timestamp untilTs,
        @Param("userId") Integer userId,
        @Param("teamId") Integer teamId,
        @Param("limitN") int limitN);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT le.request_id AS requestId,
               COALESCE(m.name, 'Model ' || le.model_id) AS modelName,
               COALESCE(p.name, 'Provider ' || le.provider_id) AS providerName,
               p.provider_type::text AS providerType,
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
                    ELSE NULL END AS totalSeconds,
               t.name AS teamName,
               u.username AS username,
               NULLIF(TRIM(COALESCE(u.prename, '') || ' ' || COALESCE(u.name, '')), '') AS fullName,
               tk.prompt_tokens AS promptTokens,
               tk.completion_tokens AS completionTokens,
               tk.total_tokens AS totalTokens,
               c.cost_micro_cents AS costMicroCents
        FROM log_entry le
        LEFT JOIN models m ON m.id = le.model_id
        LEFT JOIN providers p ON p.id = le.provider_id
        LEFT JOIN teams t ON t.id = le.team_id
        LEFT JOIN users u ON u.id = le.user_id
        LEFT JOIN LATERAL (
            SELECT MAX(CASE WHEN tt.name = 'prompt_tokens'     THEN ut.token_count END) AS prompt_tokens,
                   MAX(CASE WHEN tt.name = 'completion_tokens' THEN ut.token_count END) AS completion_tokens,
                   MAX(CASE WHEN tt.name = 'total_tokens'      THEN ut.token_count END) AS total_tokens
            FROM usage_tokens ut
            JOIN token_types tt ON tt.id = ut.type_id
            WHERE ut.log_entry_id = le.id
        ) tk ON true
        LEFT JOIN LATERAL (
            -- No COALESCE to 0: a request whose model has no token_prices row
            -- must come back as NULL so the UI can omit the cost line instead
            -- of asserting a confident "€0.00".
            SELECT SUM(
                CASE WHEN tp.price_per_k_token IS NOT NULL
                     THEN (ut.token_count::BIGINT * tp.price_per_k_token / 1000)::BIGINT
                END
            ) AS cost_micro_cents
            FROM usage_tokens ut
            LEFT JOIN LATERAL (
                SELECT price_per_k_token
                FROM token_prices
                WHERE type_id = ut.type_id
                  AND (model_id = le.model_id OR model_id IS NULL)
                  AND (provider_id = le.provider_id OR provider_id IS NULL)
                  AND valid_from <= le.timestamp_request
                ORDER BY (model_id = le.model_id) DESC NULLS LAST,
                         (provider_id = le.provider_id) DESC NULLS LAST,
                         valid_from DESC
                LIMIT 1
            ) tp ON true
            WHERE ut.log_entry_id = le.id
        ) c ON true
        WHERE le.request_id IS NOT NULL
          -- Ranged on timestamp_request, not on the COALESCE the aggregate
          -- queries use: it is NOT NULL, so the COALESCE could only ever pick
          -- another column, and the cursor below has to compare against the very
          -- column the rows are ordered by. Filter, order and cursor all
          -- agreeing on one column is what lets idx_log_entry_timestamp_request
          -- (012_log_entry_timestamp_index.xml) carry this query: it is scanned
          -- backwards for the DESC order, bounds both the range and the cursor,
          -- and stops at the LIMIT. Only the request_id tie-break is left to
          -- sort, and an incremental sort handles that within the microsecond
          -- groups it applies to.
          -- (No apostrophes in these comments: Spring Data scans the query for
          -- quoted ranges before Postgres ever sees it and reads one as an
          -- unterminated string literal.)
          AND le.timestamp_request BETWEEN :startTs AND :endTs
          AND (CAST(:userId AS INTEGER) IS NULL OR le.user_id = CAST(:userId AS INTEGER))
          AND (CAST(:teamId AS INTEGER) IS NULL OR le.team_id = CAST(:teamId AS INTEGER))
          -- Keyset cursor: everything strictly older than the last row handed
          -- out. Unlike OFFSET this neither re-walks the skipped rows nor slides
          -- when new requests arrive at the top while the operator pages.
          AND (CAST(:cursorTs AS TIMESTAMPTZ) IS NULL
               OR (le.timestamp_request, le.request_id)
                  < (CAST(:cursorTs AS TIMESTAMPTZ), CAST(:cursorId AS TEXT)))
        -- request_id breaks ties: without it two rows sharing a timestamp_request
        -- have no defined order, and the cursor comparison above could then both
        -- repeat and skip rows at a page boundary. No NULLS LAST: timestamp_request
        -- is NOT NULL, and Postgres matches an index to a sort ordering by its
        -- nulls flag rather than reasoning about the constraint, so asking for a
        -- placement the index does not have would cost the index scan.
        ORDER BY le.timestamp_request DESC, le.request_id DESC
        -- The caller sizes this and asks for one row more than it renders, which
        -- is how it knows whether a further page exists without counting. Every
        -- row costs two correlated LATERALs (one of them re-running the
        -- token_prices specificity lookup per usage_tokens row), and the live
        -- feed runs once per open stats session every 2 s.
        LIMIT :limitN
        """, nativeQuery = true)
    List<LatestRequestProjection> findLatestRequests(
        @Param("startTs") Timestamp startTs,
        @Param("endTs") Timestamp endTs,
        @Param("userId") Integer userId,
        @Param("teamId") Integer teamId,
        @Param("cursorTs") Timestamp cursorTs,
        @Param("cursorId") String cursorId,
        @Param("limitN") int limitN);

    /**
     * How many requests the range holds under the active filter — the "of N" in
     * the feed's header. The predicate has to stay identical to
     * {@link #findLatestRequests} (minus the cursor) or the count describes a
     * different set than the rows.
     */
    @Transactional(readOnly = true)
    @Query(value = """
        SELECT COUNT(*)
        FROM log_entry le
        WHERE le.request_id IS NOT NULL
          AND le.timestamp_request BETWEEN :startTs AND :endTs
          AND (CAST(:userId AS INTEGER) IS NULL OR le.user_id = CAST(:userId AS INTEGER))
          AND (CAST(:teamId AS INTEGER) IS NULL OR le.team_id = CAST(:teamId AS INTEGER))
        """, nativeQuery = true)
    Long countRequestsInRange(
        @Param("startTs") Timestamp startTs,
        @Param("endTs") Timestamp endTs,
        @Param("userId") Integer userId,
        @Param("teamId") Integer teamId);

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
        WHERE le.api_key_id IN (SELECT id FROM api_keys WHERE user_id = :userId)
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
        SELECT MAX(COALESCE(le.timestamp_forwarding, le.timestamp_request, le.timestamp_response)) AS lastTs
        FROM log_entry le
        WHERE COALESCE(le.timestamp_forwarding, le.timestamp_request, le.timestamp_response) BETWEEN :start AND :end
          AND (CAST(:userId AS INTEGER) IS NULL OR le.user_id = CAST(:userId AS INTEGER))
          AND (CAST(:teamId AS INTEGER) IS NULL OR le.team_id = CAST(:teamId AS INTEGER))
        """, nativeQuery = true)
    LastEventTsProjection findLastEventTs(
        @Param("start") Timestamp start,
        @Param("end") Timestamp end,
        @Param("userId") Integer userId,
        @Param("teamId") Integer teamId);

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
                   THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_forwarding)) END) AS avgRunSeconds,
               (SELECT COALESCE(SUM(ut.token_count), 0)
                  FROM usage_tokens ut
                  JOIN token_types tt ON tt.id = ut.type_id
                  JOIN log_entry re2 ON re2.id = ut.log_entry_id
                 WHERE tt.name = 'total_tokens'
                   AND COALESCE(re2.timestamp_forwarding, re2.timestamp_request, re2.timestamp_response) BETWEEN :start AND :end
                   -- The scope has to reach inside here too. This sum lands in
                   -- the same KPI card as the request count above, so leaving it
                   -- platform-wide would pair one team's requests with everyone's
                   -- tokens.
                   AND (CAST(:userId AS INTEGER) IS NULL OR re2.user_id = CAST(:userId AS INTEGER))
                   AND (CAST(:teamId AS INTEGER) IS NULL OR re2.team_id = CAST(:teamId AS INTEGER))
               ) AS totalTokens,
               -- "Cloud" here must mean exactly what cloudRequests above means:
               -- the statistics page shows this sum and that count in the same
               -- KPI card ("… across N cloud requests"), so a second predicate
               -- (e.g. on provider_type) would let the card pair a non-zero cost
               -- with a zero count.
               (SELECT COALESCE(SUM(
                   CASE WHEN tp.price_per_k_token IS NOT NULL
                        THEN (ut.token_count::BIGINT * tp.price_per_k_token / 1000)::BIGINT
                        ELSE 0
                   END
               ), 0)
                  FROM log_entry re3
                  JOIN providers p3 ON p3.id = re3.provider_id
                  JOIN usage_tokens ut ON ut.log_entry_id = re3.id
                  LEFT JOIN LATERAL (
                      SELECT price_per_k_token
                      FROM token_prices
                      WHERE type_id = ut.type_id
                        AND (model_id = re3.model_id OR model_id IS NULL)
                        AND (provider_id = re3.provider_id OR provider_id IS NULL)
                        AND valid_from <= re3.timestamp_request
                      ORDER BY (model_id = re3.model_id) DESC NULLS LAST,
                               (provider_id = re3.provider_id) DESC NULLS LAST,
                               valid_from DESC
                      LIMIT 1
                  ) tp ON true
                 WHERE p3.privacy_level != 'LOCAL' AND p3.privacy_level IS NOT NULL
                   AND COALESCE(re3.timestamp_forwarding, re3.timestamp_request, re3.timestamp_response) BETWEEN :start AND :end
                   AND (CAST(:userId AS INTEGER) IS NULL OR re3.user_id = CAST(:userId AS INTEGER))
                   AND (CAST(:teamId AS INTEGER) IS NULL OR re3.team_id = CAST(:teamId AS INTEGER))
               ) AS cloudCostMicroCents
        FROM log_entry le
        LEFT JOIN providers p ON p.id = le.provider_id
        WHERE COALESCE(le.timestamp_forwarding, le.timestamp_request, le.timestamp_response) BETWEEN :start AND :end
          AND (CAST(:userId AS INTEGER) IS NULL OR le.user_id = CAST(:userId AS INTEGER))
          AND (CAST(:teamId AS INTEGER) IS NULL OR le.team_id = CAST(:teamId AS INTEGER))
        """, nativeQuery = true)
    RequestLogTotalsProjection findTotals(
        @Param("start") Timestamp start,
        @Param("end") Timestamp end,
        @Param("userId") Integer userId,
        @Param("teamId") Integer teamId);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT COALESCE(le.result_status::text, 'unknown') AS status, COUNT(*) AS cnt
        FROM log_entry le
        WHERE COALESCE(le.timestamp_forwarding, le.timestamp_request, le.timestamp_response) BETWEEN :start AND :end
          AND (CAST(:userId AS INTEGER) IS NULL OR le.user_id = CAST(:userId AS INTEGER))
          AND (CAST(:teamId AS INTEGER) IS NULL OR le.team_id = CAST(:teamId AS INTEGER))
        GROUP BY 1
        """, nativeQuery = true)
    List<StatusCountProjection> findStatusCounts(
        @Param("start") Timestamp start,
        @Param("end") Timestamp end,
        @Param("userId") Integer userId,
        @Param("teamId") Integer teamId);

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
        WHERE COALESCE(re.timestamp_forwarding, re.timestamp_request, re.timestamp_response) BETWEEN :start AND :end
          AND (CAST(:userId AS INTEGER) IS NULL OR re.user_id = CAST(:userId AS INTEGER))
          AND (CAST(:teamId AS INTEGER) IS NULL OR re.team_id = CAST(:teamId AS INTEGER))
        GROUP BY re.model_id, modelName
        ORDER BY requestCount DESC
        """, nativeQuery = true)
    List<ModelBreakdownProjection> findModelBreakdown(
        @Param("start") Timestamp start,
        @Param("end") Timestamp end,
        @Param("userId") Integer userId,
        @Param("teamId") Integer teamId);

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
              AND (CAST(:userId AS INTEGER) IS NULL OR re.user_id = CAST(:userId AS INTEGER))
              AND (CAST(:teamId AS INTEGER) IS NULL OR re.team_id = CAST(:teamId AS INTEGER))
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
        @Param("bucketSec") int bucketSec,
        @Param("userId") Integer userId,
        @Param("teamId") Integer teamId);

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
          AND (CAST(:userId AS INTEGER) IS NULL OR re.user_id = CAST(:userId AS INTEGER))
          AND (CAST(:teamId AS INTEGER) IS NULL OR re.team_id = CAST(:teamId AS INTEGER))
        GROUP BY 1, re.model_id, m.name
        ORDER BY 1, modelName
        """, nativeQuery = true)
    List<ModelTimeSeriesProjection> findModelTimeSeries(
        @Param("start") Timestamp start,
        @Param("end") Timestamp end,
        @Param("bucketSec") int bucketSec,
        @Param("userId") Integer userId,
        @Param("teamId") Integer teamId);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT AVG(le.queue_depth_at_enqueue) AS avgEnqueue,
               AVG(le.queue_depth_at_schedule) AS avgSchedule,
               PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY le.queue_depth_at_enqueue) AS p95Enqueue,
               PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY le.queue_depth_at_schedule) AS p95Schedule
        FROM log_entry le
        WHERE COALESCE(le.timestamp_forwarding, le.timestamp_request, le.timestamp_response) BETWEEN :start AND :end
          AND (le.queue_depth_at_enqueue IS NOT NULL OR le.queue_depth_at_schedule IS NOT NULL)
          AND (CAST(:userId AS INTEGER) IS NULL OR le.user_id = CAST(:userId AS INTEGER))
          AND (CAST(:teamId AS INTEGER) IS NULL OR le.team_id = CAST(:teamId AS INTEGER))
        """, nativeQuery = true)
    QueueDepthProjection findQueueDepth(
        @Param("start") Timestamp start,
        @Param("end") Timestamp end,
        @Param("userId") Integer userId,
        @Param("teamId") Integer teamId);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT CASE WHEN le.was_cold_start IS TRUE THEN 'cold' ELSE 'warm' END AS kind,
               COUNT(*) AS count,
               AVG(CASE WHEN le.timestamp_forwarding IS NOT NULL AND le.timestamp_response IS NOT NULL
                   THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_forwarding)) END) AS avgRunSeconds
        FROM log_entry le
        WHERE COALESCE(le.timestamp_forwarding, le.timestamp_request, le.timestamp_response) BETWEEN :start AND :end
          AND (CAST(:userId AS INTEGER) IS NULL OR le.user_id = CAST(:userId AS INTEGER))
          AND (CAST(:teamId AS INTEGER) IS NULL OR le.team_id = CAST(:teamId AS INTEGER))
        GROUP BY kind
        """, nativeQuery = true)
    List<RuntimeByColdStartProjection> findRuntimeByColdStart(
        @Param("start") Timestamp start,
        @Param("end") Timestamp end,
        @Param("userId") Integer userId,
        @Param("teamId") Integer teamId);
}
