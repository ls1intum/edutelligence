package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import de.tum.cit.aet.logos.logoswebservice.identity.dto.ReplaceApplicationKeyQueueRanksRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApplicationKeyQueueRank;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApplicationKeyQueueRankRepository;

@Service
public class ApplicationKeyQueueRankService {

    private final ApplicationKeyQueueRankRepository rankRepository;
    private final ApiKeyRepository apiKeyRepository;
    private final JdbcTemplate jdbc;

    public ApplicationKeyQueueRankService(ApplicationKeyQueueRankRepository rankRepository,
                                          ApiKeyRepository apiKeyRepository,
                                          JdbcTemplate jdbc) {
        this.rankRepository = rankRepository;
        this.apiKeyRepository = apiKeyRepository;
        this.jdbc = jdbc;
    }

    public List<Map<String, Object>> listRanks() {
        return jdbc.query("""
            SELECT r.api_key_id,
                   r.rank,
                   k.name AS key_name,
                   k.team_id,
                   t.name AS team_name,
                   k.environment,
                   k.default_priority
              FROM application_key_queue_ranks r
              JOIN api_keys k ON k.id = r.api_key_id
              LEFT JOIN teams t ON t.id = k.team_id
             ORDER BY r.rank ASC
            """, (rs, rowNum) -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("api_key_id", rs.getInt("api_key_id"));
            m.put("rank", rs.getInt("rank"));
            m.put("key_name", rs.getString("key_name"));
            m.put("team_id", rs.getObject("team_id") != null ? rs.getInt("team_id") : null);
            m.put("team_name", rs.getString("team_name"));
            m.put("environment", rs.getString("environment"));
            m.put("default_priority", rs.getInt("default_priority"));
            return m;
        });
    }

    @Transactional
    public List<Map<String, Object>> replaceRanks(ReplaceApplicationKeyQueueRanksRequestDTO body,
                                                  Integer updatedBy) {
        List<Integer> apiKeyIds = body == null || body.apiKeyIds() == null
            ? List.of()
            : body.apiKeyIds();
        Set<Integer> seen = new HashSet<>();
        List<Integer> ordered = new ArrayList<>();
        for (Integer id : apiKeyIds) {
            if (id == null) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "api_key_ids must not contain null");
            }
            if (!seen.add(id)) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "api_key_ids must not contain duplicates: " + id);
            }
            ordered.add(id);
        }

        if (!ordered.isEmpty()) {
            List<ApiKey> keys = apiKeyRepository.findAllById(ordered);
            Map<Integer, ApiKey> byId = new LinkedHashMap<>();
            for (ApiKey key : keys) {
                byId.put(key.getId(), key);
            }
            for (Integer id : ordered) {
                ApiKey key = byId.get(id);
                if (key == null) {
                    throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "API key not found: " + id);
                }
                if (key.getKeyType() != ApiKeyType.application) {
                    throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                        "API key " + id + " is not key_type=application");
                }
            }
        }

        // One shared ranking: serialize whole replacements, including on an
        // empty table, so two of them cannot both insert rank 1.
        jdbc.execute("LOCK TABLE application_key_queue_ranks IN SHARE ROW EXCLUSIVE MODE");
        rankRepository.deleteAllInBatch();
        rankRepository.flush();
        Instant now = Instant.now();
        List<ApplicationKeyQueueRank> rows = new ArrayList<>();
        for (int i = 0; i < ordered.size(); i++) {
            ApplicationKeyQueueRank row = new ApplicationKeyQueueRank();
            row.setApiKeyId(ordered.get(i));
            row.setRank(i + 1);
            row.setUpdatedAt(now);
            row.setUpdatedBy(updatedBy);
            rows.add(row);
        }
        if (!rows.isEmpty()) {
            rankRepository.saveAll(rows);
            rankRepository.flush();
        }
        return listRanks();
    }
}
