package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Model;

public interface ModelRepository extends JpaRepository<Model, Integer> {

    boolean existsByNameIgnoreCase(String name);

    List<Model> findByNameIgnoreCase(String name);

    @Query(value = """
        SELECT m.id, m.name, m.weight_latency, m.weight_accuracy, m.weight_cost,
               m.weight_quality, m.tags, m.description,
               (SELECT string_agg(a.alias, ', ' ORDER BY a.alias)
                FROM model_aliases a
                WHERE a.model_id = m.id
               ) AS aliases,
               (SELECT ROUND(tp.price_per_k_token::NUMERIC / 100000, 4)
                FROM token_prices tp JOIN token_types tt ON tt.id = tp.type_id
                WHERE (tp.model_id = m.id OR tp.model_id IS NULL)
                  AND tt.name = 'prompt_tokens' AND tp.valid_from <= NOW()
                ORDER BY (tp.model_id = m.id) DESC NULLS LAST, tp.valid_from DESC LIMIT 1
               ) AS input_usd_per_million,
               (SELECT ROUND(tp.price_per_k_token::NUMERIC / 100000, 4)
                FROM token_prices tp JOIN token_types tt ON tt.id = tp.type_id
                WHERE (tp.model_id = m.id OR tp.model_id IS NULL)
                  AND tt.name = 'completion_tokens' AND tp.valid_from <= NOW()
                ORDER BY (tp.model_id = m.id) DESC NULLS LAST, tp.valid_from DESC LIMIT 1
               ) AS output_usd_per_million,
               (SELECT MAX(le.timestamp_request)
                FROM log_entry le
                WHERE le.model_id = m.id
               ) AS last_used_at,
               m.weight_overrides::text AS weight_overrides_text
        FROM models m ORDER BY m.id
        """, nativeQuery = true)
    List<ModelWithPriceProjection> findAllWithPricing();

    @Query(value = """
        WITH effective_model_ids AS (
            SELECT DISTINCT m.id
            FROM models m
            JOIN team_model_permissions tmp ON m.id = tmp.model_id
            JOIN team_members tm ON tmp.team_id = tm.team_id
            JOIN model_provider mp ON m.id = mp.model_id
            JOIN team_provider_permissions tpp ON mp.provider_id = tpp.provider_id AND tpp.team_id = tm.team_id
            WHERE tm.user_id = :userId
            UNION
            SELECT DISTINCT akmp.model_id
            FROM api_key_model_permissions akmp
            JOIN api_keys ak ON akmp.api_key_id = ak.id
            JOIN model_provider mp ON akmp.model_id = mp.model_id
            JOIN api_key_provider_permissions akpp ON akpp.api_key_id = ak.id AND akpp.provider_id = mp.provider_id
            WHERE ak.user_id = :userId AND ak.is_active = true AND ak.use_custom_permissions = true
        )
        -- last_used_at is deliberately not computed here: it is only exposed to
        -- Logos admins (see ModelService), so the per-model MAX subselect would
        -- be wasted work on every other model list request.
        SELECT DISTINCT m.id, m.name, m.weight_latency, m.weight_accuracy, m.weight_cost,
               m.weight_quality, m.tags, m.description,
               (SELECT string_agg(a.alias, ', ' ORDER BY a.alias)
                FROM model_aliases a
                WHERE a.model_id = m.id
               ) AS aliases,
               (SELECT ROUND(tp.price_per_k_token::NUMERIC / 100000, 4)
                FROM token_prices tp JOIN token_types tt ON tt.id = tp.type_id
                WHERE (tp.model_id = m.id OR tp.model_id IS NULL)
                  AND tt.name = 'prompt_tokens' AND tp.valid_from <= NOW()
                ORDER BY (tp.model_id = m.id) DESC NULLS LAST, tp.valid_from DESC LIMIT 1
               ) AS input_usd_per_million,
               (SELECT ROUND(tp.price_per_k_token::NUMERIC / 100000, 4)
                FROM token_prices tp JOIN token_types tt ON tt.id = tp.type_id
                WHERE (tp.model_id = m.id OR tp.model_id IS NULL)
                  AND tt.name = 'completion_tokens' AND tp.valid_from <= NOW()
                ORDER BY (tp.model_id = m.id) DESC NULLS LAST, tp.valid_from DESC LIMIT 1
               ) AS output_usd_per_million,
               m.weight_overrides::text AS weight_overrides_text
        FROM models m
        JOIN effective_model_ids em ON m.id = em.id
        ORDER BY m.id
        """, nativeQuery = true)
    List<ModelWithPriceProjection> findAllWithPricingForUser(@Param("userId") Integer userId);

    /**
     * Auto-derivation weight write: the WHERE clause re-checks the override
     * map at write time, so a dimension an admin pinned concurrently with the
     * derivation run is left untouched (no @Version on the entity).
     */
    @Transactional
    @Modifying
    @Query(value = "UPDATE models SET weight_latency = :weight "
        + "WHERE id = :id AND NOT weight_overrides @> '{\"latency\": true}'", nativeQuery = true)
    int updateWeightLatencyGuarded(@Param("id") int id, @Param("weight") int weight);

    @Transactional
    @Modifying
    @Query(value = "UPDATE models SET weight_cost = :weight "
        + "WHERE id = :id AND NOT weight_overrides @> '{\"cost\": true}'", nativeQuery = true)
    int updateWeightCostGuarded(@Param("id") int id, @Param("weight") int weight);
}
