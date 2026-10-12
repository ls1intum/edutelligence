package de.tum.cit.aet.logos.logoswebservice.operations.repository;

import java.sql.Timestamp;
import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.operations.entity.LogEntry;

/**
 * Queries behind the public statistics page (the unauthenticated GET /stats).
 *
 * <p>Separate from {@link LogEntryRepository} on purpose: that interface's
 * queries all share one documented shape — a nullable user/team/provider
 * scope plus an {@code errorsOnly} flag over every row the caller names — and
 * these three cannot be spelled in it. The public page aggregates
 * <em>successful</em> requests only (a platform showcase, not an operations
 * view, so failures would read as the platform underperforming), and its scope
 * is a set rather than a single id: every team whose
 * {@code share_public_stats} is true. Folding both into the shared queries
 * would add a second copy of each predicate that could drift from the filtered
 * one, which is what the shared queries were built to avoid.
 *
 * <p>They read {@code log_entry} directly, without the hourly rollup the
 * statistics aggregates use: the public page is fetched once per visit rather
 * than pushed every two seconds, so the rollup's savings never pay for its
 * complexity here. The window the service allows (at most 90 days) is bounded
 * on the COALESCE the index {@code idx_log_entry_effective_ts} (035) carries,
 * and the team set is small enough to inline as a subquery on every row.
 */
public interface PublicStatsRepository extends JpaRepository<LogEntry, Integer> {

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT COUNT(*)::bigint AS requests,
               COALESCE(SUM(tok.total_tokens), 0)::bigint AS totalTokens
        FROM log_entry le
        LEFT JOIN LATERAL (
            SELECT SUM(ut.token_count) AS total_tokens
            FROM usage_tokens ut
            JOIN token_types tt ON tt.id = ut.type_id
            WHERE ut.log_entry_id = le.id AND tt.name = 'total_tokens'
        ) tok ON TRUE
        WHERE le.result_status = 'success'
          AND le.team_id IN (SELECT id FROM teams WHERE share_public_stats = TRUE)
          AND COALESCE(le.timestamp_forwarding, le.timestamp_request, le.timestamp_response) BETWEEN :start AND :end
        """, nativeQuery = true)
    PublicStatsTotalsProjection findTotals(
        @Param("start") Timestamp start,
        @Param("end") Timestamp end);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT le.model_id AS modelId,
               COALESCE(m.name, le.model_name, 'Model ' || le.model_id) AS modelName,
               COUNT(*)::bigint AS requestCount
        FROM log_entry le
        LEFT JOIN models m ON m.id = le.model_id
        WHERE le.result_status = 'success'
          AND le.team_id IN (SELECT id FROM teams WHERE share_public_stats = TRUE)
          AND (le.model_id IS NOT NULL OR le.model_name IS NOT NULL)
          AND COALESCE(le.timestamp_forwarding, le.timestamp_request, le.timestamp_response) BETWEEN :start AND :end
        GROUP BY le.model_id, COALESCE(m.name, le.model_name, 'Model ' || le.model_id)
        ORDER BY requestCount DESC, modelName
        """, nativeQuery = true)
    List<PublicStatsModelProjection> findModelBreakdown(
        @Param("start") Timestamp start,
        @Param("end") Timestamp end);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT EXTRACT(EPOCH FROM to_timestamp(FLOOR(EXTRACT(EPOCH FROM COALESCE(
                   le.timestamp_forwarding, le.timestamp_request, le.timestamp_response)) / 86400) * 86400))
               AS bucketTs,
               COUNT(*)::bigint AS requestCount
        FROM log_entry le
        WHERE le.result_status = 'success'
          AND le.team_id IN (SELECT id FROM teams WHERE share_public_stats = TRUE)
          AND COALESCE(le.timestamp_forwarding, le.timestamp_request, le.timestamp_response) BETWEEN :start AND :end
        GROUP BY 1
        ORDER BY 1
        """, nativeQuery = true)
    List<PublicStatsTimeSeriesProjection> findTimeSeries(
        @Param("start") Timestamp start,
        @Param("end") Timestamp end);
}
