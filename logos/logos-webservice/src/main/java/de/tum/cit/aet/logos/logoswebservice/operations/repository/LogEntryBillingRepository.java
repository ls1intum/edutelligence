package de.tum.cit.aet.logos.logoswebservice.operations.repository;

import java.sql.Timestamp;
import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.operations.entity.LogEntry;

public interface LogEntryBillingRepository extends JpaRepository<LogEntry, Integer> {

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT t.id AS teamId,
               t.name AS teamName,
               NULL AS apiKeyId,
               NULL AS apiKeyName,
               DATE_TRUNC(:interval, le.timestamp_request) AS bucketTs,
               COALESCE(SUM(
                   CASE WHEN tp.price_per_k_token IS NOT NULL
                        THEN (ut.token_count::BIGINT * tp.price_per_k_token / 1000)::BIGINT
                        ELSE 0
                   END
               ), 0) AS costMicroCents
        FROM log_entry le
        JOIN api_keys ak ON ak.id = le.api_key_id
        JOIN teams t ON t.id = ak.team_id
        JOIN usage_tokens ut ON ut.log_entry_id = le.id
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
        WHERE le.timestamp_request >= :startTs AND le.timestamp_request < :endTs
          AND le.api_key_id IS NOT NULL
        GROUP BY 1, 2, 5
        ORDER BY bucketTs, t.name
        """, nativeQuery = true)
    List<BudgetBucketProjection> findTeamBudgetHistory(
        @Param("startTs") Timestamp startTs,
        @Param("endTs") Timestamp endTs,
        @Param("interval") String interval);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT NULL AS teamId,
               NULL AS teamName,
               ak.id AS apiKeyId,
               ak.name AS apiKeyName,
               DATE_TRUNC(:interval, le.timestamp_request) AS bucketTs,
               COALESCE(SUM(
                   CASE WHEN tp.price_per_k_token IS NOT NULL
                        THEN (ut.token_count::BIGINT * tp.price_per_k_token / 1000)::BIGINT
                        ELSE 0
                   END
               ), 0) AS costMicroCents
        FROM log_entry le
        JOIN api_keys ak ON ak.id = le.api_key_id
        JOIN usage_tokens ut ON ut.log_entry_id = le.id
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
        WHERE ak.team_id = :teamId
          AND le.timestamp_request >= :startTs AND le.timestamp_request < :endTs
          AND le.api_key_id IS NOT NULL
        GROUP BY 3, 4, 5
        ORDER BY bucketTs, ak.name
        """, nativeQuery = true)
    List<BudgetBucketProjection> findKeyBudgetHistory(
        @Param("teamId") int teamId,
        @Param("startTs") Timestamp startTs,
        @Param("endTs") Timestamp endTs,
        @Param("interval") String interval);
}
