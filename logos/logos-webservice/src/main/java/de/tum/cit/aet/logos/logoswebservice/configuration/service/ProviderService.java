package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.AddProviderRequest;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.ConnectModelProviderRequest;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.DisconnectModelProviderRequest;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.UpdateProviderRequest;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.CloudProviderType;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Provider;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ProviderType;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ThresholdLevel;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ProviderRepository;

@Service
public class ProviderService {

    private static final Set<String> VALID_PRIVACY_LEVELS = Set.of(
        "LOCAL", "CLOUD_IN_EU_BY_EU_PROVIDER",
        "CLOUD_IN_EU_BY_US_PROVIDER", "CLOUD_NOT_IN_EU_BY_US_PROVIDER"
    );

    private static final String ADMIN_PROVIDERS_SQL = """
        SELECT id, name, base_url, api_key, provider_type::text, cloud_provider_type::text,
               privacy_level::text, auth_name, auth_format
        FROM providers ORDER BY name ASC, id ASC
        """;

    private static final String FILTERED_PROVIDERS_SQL = """
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
        )
        SELECT DISTINCT p.id, p.name, p.base_url, p.api_key, p.provider_type::text,
               p.cloud_provider_type::text, p.privacy_level::text, p.auth_name, p.auth_format
        FROM providers p JOIN effective_providers ep ON p.id = ep.provider_id
        ORDER BY p.name ASC
        """;

    private static final String PROVIDER_MODELS_SQL = """
        SELECT m.id AS model_id, m.name AS model_name, mp.endpoint, mp.api_key
        FROM model_provider mp JOIN models m ON m.id = mp.model_id
        WHERE mp.provider_id = ? ORDER BY m.name ASC
        """;

    private static final String CONNECT_UPSERT_SQL = """
        INSERT INTO model_provider (provider_id, model_id, api_key, endpoint)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (model_id, provider_id) DO UPDATE
          SET api_key = EXCLUDED.api_key, endpoint = EXCLUDED.endpoint
        RETURNING id
        """;

    private final ProviderRepository providerRepository;
    private final JdbcTemplate jdbcTemplate;

    public ProviderService(ProviderRepository providerRepository, JdbcTemplate jdbcTemplate) {
        this.providerRepository = providerRepository;
        this.jdbcTemplate = jdbcTemplate;
    }

    public List<Map<String, Object>> getProviders(AuthContext auth) {
        boolean admin = "logos_admin".equals(auth.role());
        return admin
            ? jdbcTemplate.query(ADMIN_PROVIDERS_SQL, (rs, n) -> toProviderMap(rs))
            : jdbcTemplate.query(FILTERED_PROVIDERS_SQL, (rs, n) -> toProviderMap(rs), auth.keyValue());
    }

    @Transactional
    public Map<String, Object> addProvider(AddProviderRequest req) {
        if (req.privacyLevel() == null || !VALID_PRIVACY_LEVELS.contains(req.privacyLevel())) {
            throw new IllegalArgumentException("privacy_level is required and must be one of " + VALID_PRIVACY_LEVELS);
        }
        Provider p = new Provider();
        p.setName(req.providerName());
        p.setBaseUrl(req.baseUrl());
        p.setApiKey(req.apiKey());
        p.setAuthName(req.authName() != null ? req.authName() : "");
        p.setAuthFormat(req.authFormat() != null ? req.authFormat() : "");
        p.setProviderType(parseProviderType(req.providerType()));
        p.setCloudProviderType(parseCloudProviderType(req.cloudProviderType()));
        p.setPrivacyLevel(ThresholdLevel.valueOf(req.privacyLevel()));
        p = providerRepository.save(p);
        return Map.of("result", "Created Provider.", "provider-id", p.getId());
    }

    @Transactional
    public Map<String, Object> updateProvider(UpdateProviderRequest req) {
        Provider p = providerRepository.findById(req.providerId())
            .orElseThrow(() -> new IllegalArgumentException("Provider not found: " + req.providerId()));
        if (req.providerName() != null) p.setName(req.providerName());
        if (req.baseUrl() != null) p.setBaseUrl(req.baseUrl());
        if (req.apiKey() != null) p.setApiKey(req.apiKey());
        if (req.authName() != null) p.setAuthName(req.authName());
        if (req.authFormat() != null) p.setAuthFormat(req.authFormat());
        if (req.providerType() != null) p.setProviderType(parseProviderType(req.providerType()));
        if (req.cloudProviderType() != null) p.setCloudProviderType(parseCloudProviderType(req.cloudProviderType()));
        if (req.privacyLevel() != null) {
            if (!VALID_PRIVACY_LEVELS.contains(req.privacyLevel())) {
                throw new IllegalArgumentException("Invalid privacy_level");
            }
            p.setPrivacyLevel(ThresholdLevel.valueOf(req.privacyLevel()));
        }
        providerRepository.save(p);
        return Map.of("result", "Updated Provider.");
    }

    @Transactional
    public Map<String, Object> deleteProvider(Integer providerId) {
        if (!providerRepository.existsById(providerId)) {
            throw new IllegalArgumentException("Provider not found: " + providerId);
        }
        providerRepository.deleteById(providerId);
        return Map.of("result", "Deleted Provider.");
    }

    public Map<String, Object> connectModelProvider(ConnectModelProviderRequest req) {
        Integer id = jdbcTemplate.queryForObject(
            CONNECT_UPSERT_SQL,
            Integer.class,
            req.providerId(), req.modelId(),
            req.apiKey(), req.endpoint()
        );
        return Map.of("result", "Connected Model to Provider. ID: " + id + ".");
    }

    @Transactional
    public Map<String, Object> disconnectModelProvider(DisconnectModelProviderRequest req) {
        int deleted = jdbcTemplate.update(
            "DELETE FROM model_provider WHERE model_id = ? AND provider_id = ?",
            req.modelId(), req.providerId()
        );
        if (deleted == 0) {
            throw new IllegalArgumentException("Connection not found.");
        }
        return Map.of("result", "Disconnected model from provider.");
    }

    public List<Map<String, Object>> getProviderModels(Integer providerId) {
        return jdbcTemplate.query(PROVIDER_MODELS_SQL, (rs, n) -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("model_id", rs.getInt("model_id"));
            m.put("model_name", rs.getString("model_name"));
            m.put("endpoint", rs.getString("endpoint") != null ? rs.getString("endpoint") : "");
            m.put("api_key", rs.getString("api_key") != null ? rs.getString("api_key") : "");
            return m;
        }, providerId);
    }

    public Map<String, Object> getGeneralProviderStats() {
        long count = providerRepository.count();
        return Map.of("totalProviders", count);
    }

    private static ProviderType parseProviderType(String raw) {
        if (raw == null) return ProviderType.logosnode;
        String normalized = raw.toLowerCase();
        if (List.of("node", "node_controller", "ollama", "logos_worker_node").contains(normalized)) {
            return ProviderType.logosnode;
        }
        try { return ProviderType.valueOf(normalized); }
        catch (IllegalArgumentException e) { return ProviderType.logosnode; }
    }

    private static CloudProviderType parseCloudProviderType(String raw) {
        if (raw == null || raw.equalsIgnoreCase("none")) return null;
        try { return CloudProviderType.valueOf(raw.toLowerCase()); }
        catch (IllegalArgumentException e) { return null; }
    }

    private static Map<String, Object> toProviderMap(ResultSet rs) throws SQLException {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", rs.getInt("id"));
        m.put("name", rs.getString("name"));
        m.put("base_url", rs.getString("base_url"));
        m.put("api_key", rs.getString("api_key"));
        m.put("provider_type", rs.getString("provider_type"));
        m.put("cloud_provider_type", rs.getString("cloud_provider_type"));
        m.put("privacy_level", rs.getString("privacy_level"));
        m.put("auth_name", rs.getString("auth_name"));
        m.put("auth_format", rs.getString("auth_format"));
        return m;
    }
}