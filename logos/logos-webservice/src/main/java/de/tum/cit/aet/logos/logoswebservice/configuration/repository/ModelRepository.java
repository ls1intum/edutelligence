package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Model;

public interface ModelRepository extends JpaRepository<Model, Integer> {

    @Query(value = """
        SELECT m.id, m.name, m.weight_latency, m.weight_accuracy, m.weight_cost,
               m.weight_quality, m.tags, m.parallel, m.description,
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
               ) AS output_usd_per_million
        FROM models m ORDER BY m.id
        """, nativeQuery = true)
    List<ModelWithPriceProjection> findAllWithPricing();

    @Query(value = """
        WITH key_info AS (
            SELECT ak.id AS aki, ak.team_id AS tid, ak.use_custom_permissions AS custom
            FROM api_keys ak WHERE ak.key_value = :keyValue AND ak.is_active = true
        ),
        effective_providers AS (
            SELECT akpp.provider_id FROM api_key_provider_permissions akpp, key_info ki
            WHERE akpp.api_key_id = ki.aki AND ki.custom = true
            UNION
            SELECT tpp.provider_id FROM team_provider_permissions tpp, key_info ki
            WHERE tpp.team_id = ki.tid AND ki.custom = false
        ),
        effective_models AS (
            SELECT akmp.model_id FROM api_key_model_permissions akmp, key_info ki
            WHERE akmp.api_key_id = ki.aki AND ki.custom = true
            UNION
            SELECT tmp.model_id FROM team_model_permissions tmp, key_info ki
            WHERE tmp.team_id = ki.tid AND ki.custom = false
        )
        SELECT DISTINCT m.id, m.name, m.weight_latency, m.weight_accuracy, m.weight_cost,
               m.weight_quality, m.tags, m.parallel, m.description,
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
               ) AS output_usd_per_million
        FROM models m
        JOIN effective_models em ON m.id = em.model_id
        JOIN model_provider mp ON m.id = mp.model_id
        JOIN effective_providers ep ON mp.provider_id = ep.provider_id
        ORDER BY m.id
        """, nativeQuery = true)
    List<ModelWithPriceProjection> findAllWithPricingForKey(@Param("keyValue") String keyValue);
}
