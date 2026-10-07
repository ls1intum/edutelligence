package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Service;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ProviderType;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.KeyTypeRequestCountProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.LogEntryRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.ProviderTypeRequestCountProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.TeamRequestCountProjection;

@Service
public class StatsService {

    private final ModelRepository modelRepository;
    private final ApiKeyRepository apiKeyRepository;
    private final ProviderRepository providerRepository;
    private final LogEntryRepository logEntryRepository;
    private final TeamRepository teamRepository;
    private final UserRepository userRepository;

    public StatsService(ModelRepository modelRepository,
                        ApiKeyRepository apiKeyRepository,
                        ProviderRepository providerRepository,
                        LogEntryRepository logEntryRepository,
                        TeamRepository teamRepository,
                        UserRepository userRepository) {
        this.modelRepository = modelRepository;
        this.apiKeyRepository = apiKeyRepository;
        this.providerRepository = providerRepository;
        this.logEntryRepository = logEntryRepository;
        this.teamRepository = teamRepository;
        this.userRepository = userRepository;
    }

    public Map<String, Object> generalStats() {
        long models = modelRepository.count();
        long apiKeys = apiKeyRepository.countByIsActive(true);
        long requests = logEntryRepository.count();
        long providers = providerRepository.count();
        long teams = teamRepository.count();
        return Map.of("models", models, "api_keys", apiKeys, "requests", requests, "providers", providers, "teams", teams);
    }

    public Map<String, Object> generalModelStats() {
        return Map.of("totalModels", modelRepository.count());
    }

    public Map<String, Object> generalProviderStats() {
        return Map.of("totalProviders", providerRepository.count());
    }

    /**
     * Platform-wide figures for the public stats page — the one part of the
     * platform reachable without a credential.
     *
     * <p>Only aggregate counts leave the service: no request rows, no key
     * values, no user names. Every request figure counts settled successes
     * only — what the platform actually delivered — while errors and timeouts
     * stay on the admin statistics page, where they are an operational
     * concern. "Students" are the registered users still active; a user only
     * becomes inactive once their Keycloak account is gone.
     */
    public Map<String, Object> publicStats() {
        long students = userRepository.countByIsActiveTrue();
        long teams = teamRepository.count();

        List<Map<String, Object>> requestsPerTeam = new ArrayList<>();
        long successfulRequests = 0;
        for (TeamRequestCountProjection row : logEntryRepository.countSuccessfulByTeam()) {
            Map<String, Object> team = new LinkedHashMap<>();
            team.put("team_id", row.getTeamId());
            team.put("team_name", row.getTeamName());
            team.put("requests", row.getRequests());
            requestsPerTeam.add(team);
            successfulRequests += row.getRequests();
        }

        Map<String, Long> requestsByKeyType = new LinkedHashMap<>();
        for (ApiKeyType type : ApiKeyType.values()) {
            requestsByKeyType.put(type.name(), 0L);
        }
        // Rows whose API key was deleted land here so the key-type split still
        // adds up to successful_requests.
        requestsByKeyType.put("unknown", 0L);
        for (KeyTypeRequestCountProjection row : logEntryRepository.countSuccessfulByKeyType()) {
            String keyType = row.getKeyType() == null ? "unknown" : row.getKeyType();
            requestsByKeyType.merge(keyType, row.getRequests(), Long::sum);
        }

        // ProviderType.logosnode is the self-hosted lane; everything else with
        // a known provider is a forwarded cloud deployment. Deleted providers
        // (provider_id SET NULL) keep an explicit unknown bucket so the lane
        // chart still matches the headline total.
        Map<String, Long> localCloud = new LinkedHashMap<>();
        localCloud.put("local", 0L);
        localCloud.put("cloud", 0L);
        localCloud.put("unknown", 0L);
        for (ProviderTypeRequestCountProjection row : logEntryRepository.countSuccessfulByProviderType()) {
            String providerType = row.getProviderType();
            String lane;
            if (providerType == null || "unknown".equals(providerType)) {
                lane = "unknown";
            } else if (ProviderType.logosnode.name().equals(providerType)) {
                lane = "local";
            } else {
                lane = "cloud";
            }
            localCloud.merge(lane, row.getRequests(), Long::sum);
        }

        double averageRequestsPerUser = students == 0 ? 0.0 : Math.round(successfulRequests * 100.0 / students) / 100.0;

        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("students", students);
        stats.put("teams", teams);
        stats.put("successful_requests", successfulRequests);
        stats.put("average_requests_per_user", averageRequestsPerUser);
        stats.put("requests_per_team", requestsPerTeam);
        stats.put("requests_by_key_type", requestsByKeyType);
        stats.put("local_cloud_requests", localCloud);
        return stats;
    }
}
