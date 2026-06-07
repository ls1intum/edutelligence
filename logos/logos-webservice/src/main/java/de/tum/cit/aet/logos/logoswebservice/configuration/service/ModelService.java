package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.AddModelRequest;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.UpdateModelRequest;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Model;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;

@Service
public class ModelService {

    private static final String ADMIN_MODELS_SQL = """
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
        """;

    private static final String FILTERED_MODELS_SQL = """
        WITH key_info AS (
            SELECT ak.id AS aki, ak.team_id AS tid, ak.use_custom_permissions AS custom
            FROM api_keys ak WHERE ak.key_value = ? AND ak.is_active = true
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
        """;

    private final ModelRepository modelRepository;
    private final ModelWeightService weightService;
    private final JdbcTemplate jdbcTemplate;

    public ModelService(ModelRepository modelRepository, ModelWeightService weightService,
                        JdbcTemplate jdbcTemplate) {
        this.modelRepository = modelRepository;
        this.weightService = weightService;
        this.jdbcTemplate = jdbcTemplate;
    }

    public List<Map<String, Object>> getModels(AuthContext auth) {
        boolean admin = isAdmin(auth);
        List<Map<String, Object>> rows = admin
            ? jdbcTemplate.query(ADMIN_MODELS_SQL, (rs, n) -> toModelMap(rs))
            : jdbcTemplate.query(FILTERED_MODELS_SQL, (rs, n) -> toModelMap(rs), auth.keyValue());
        return rows;
    }

    @Transactional
    public Map<String, Object> addModel(AddModelRequest req) {
        Model model = new Model();
        model.setName(req.name());
        model.setTags(req.tags() != null ? req.tags() : "");
        model.setParallel(req.parallel() != null ? req.parallel() : 1);
        model.setDescription(req.description() != null ? req.description() : "");
        model.setWeightLatency(0);
        model.setWeightAccuracy(0);
        model.setWeightCost(0);
        model.setWeightQuality(0);
        model = modelRepository.save(model);
        weightService.rebalanceAfterAdd(
            model.getId(),
            req.worseLatencyId(), req.worseAccuracyId(),
            req.worseCostId(), req.worseQualityId()
        );
        return Map.of("result", "Created Model", "model_id", model.getId());
    }

    @Transactional
    public Map<String, Object> updateModelInfo(UpdateModelRequest req) {
        Model model = modelRepository.findById(req.modelId())
            .orElseThrow(() -> new IllegalArgumentException("Model not found: " + req.modelId()));
        if (req.name() != null) model.setName(req.name());
        if (req.description() != null) model.setDescription(req.description());
        if (req.tags() != null) model.setTags(req.tags());
        if (req.parallel() != null) model.setParallel(req.parallel());
        if (req.weightLatency() != null) model.setWeightLatency(req.weightLatency());
        if (req.weightAccuracy() != null) model.setWeightAccuracy(req.weightAccuracy());
        if (req.weightCost() != null) model.setWeightCost(req.weightCost());
        if (req.weightQuality() != null) model.setWeightQuality(req.weightQuality());
        modelRepository.save(model);
        return Map.of("result", "Model updated");
    }

    @Transactional
    public Map<String, Object> deleteModel(Integer id) {
        if (!modelRepository.existsById(id)) {
            throw new IllegalArgumentException("Model not found: " + id);
        }
        weightService.rebalanceAfterDelete(id);
        return Map.of("result", "Deleted Model");
    }

    public Optional<Map<String, Object>> getModel(Integer id) {
        return modelRepository.findById(id).map(m -> {
            Map<String, Object> map = new LinkedHashMap<>();
            map.put("id", m.getId());
            map.put("name", m.getName() != null ? m.getName() : "Model " + m.getId());
            map.put("weight_latency", m.getWeightLatency());
            map.put("weight_accuracy", m.getWeightAccuracy());
            map.put("weight_cost", m.getWeightCost());
            map.put("weight_quality", m.getWeightQuality());
            map.put("tags", m.getTags());
            map.put("parallel", m.getParallel());
            map.put("description", m.getDescription());
            return map;
        });
    }

    @Transactional
    public Map<String, Object> updateModelWeight(int id, String category, int feedback) {
        if (!modelRepository.existsById(id)) {
            throw new IllegalArgumentException("Model not found: " + id);
        }
        weightService.rebalanceAfterFeedback(id, category, feedback);
        return Map.of("result", "Updated Model");
    }

    public Map<String, Object> getGeneralModelStats() {
        long count = modelRepository.count();
        return Map.of("totalModels", count);
    }

    private static boolean isAdmin(AuthContext auth) {
        return "logos_admin".equals(auth.role()) || "app_admin".equals(auth.role());
    }

    private static Map<String, Object> toModelMap(java.sql.ResultSet rs) throws java.sql.SQLException {
        Map<String, Object> m = new LinkedHashMap<>();
        int id = rs.getInt("id");
        String name = rs.getString("name");
        m.put("id", id);
        m.put("name", name != null ? name : "Model " + id);
        m.put("weight_latency", rs.getObject("weight_latency"));
        m.put("weight_accuracy", rs.getObject("weight_accuracy"));
        m.put("weight_cost", rs.getObject("weight_cost"));
        m.put("weight_quality", rs.getObject("weight_quality"));
        m.put("tags", rs.getString("tags"));
        m.put("parallel", rs.getObject("parallel"));
        m.put("description", rs.getString("description"));
        m.put("input_usd_per_million", rs.getObject("input_usd_per_million"));
        m.put("output_usd_per_million", rs.getObject("output_usd_per_million"));
        return m;
    }
}
