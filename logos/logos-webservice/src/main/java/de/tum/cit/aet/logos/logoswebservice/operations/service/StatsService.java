package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.sql.Timestamp;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ProviderType;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.AgentSessionDayProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.KeyTypeRequestCountProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.LogEntryRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.ProviderTypeRequestCountProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.PublicUsageRowProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.TeamRequestCountProjection;

@Service
public class StatsService {

    /** Allowed rolling windows for GET /public/stats?days=… (plus {@code all}). */
    public static final Set<String> PUBLIC_STATS_DAY_OPTIONS = Set.of("7", "30", "90", "365", "all");

    private final ModelRepository modelRepository;
    private final ApiKeyRepository apiKeyRepository;
    private final ProviderRepository providerRepository;
    private final LogEntryRepository logEntryRepository;
    private final TeamRepository teamRepository;

    public StatsService(ModelRepository modelRepository,
                        ApiKeyRepository apiKeyRepository,
                        ProviderRepository providerRepository,
                        LogEntryRepository logEntryRepository,
                        TeamRepository teamRepository) {
        this.modelRepository = modelRepository;
        this.apiKeyRepository = apiKeyRepository;
        this.providerRepository = providerRepository;
        this.logEntryRepository = logEntryRepository;
        this.teamRepository = teamRepository;
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
     * Resolves the public-stats {@code days} query value to a lower bound, or
     * null for all time. Allowed values are 7, 30, 90, 365 and {@code all};
     * anything else is rejected. Null or blank defaults to 30.
     */
    public static Timestamp resolvePublicStatsSince(String days) {
        String normalized = (days == null || days.isBlank()) ? "30" : days.trim().toLowerCase();
        if (!PUBLIC_STATS_DAY_OPTIONS.contains(normalized)) {
            throw new IllegalArgumentException(
                "days must be one of 7, 30, 90, 365, or all");
        }
        if ("all".equals(normalized)) {
            return null;
        }
        int window = Integer.parseInt(normalized);
        return Timestamp.from(Instant.now().minus(window, ChronoUnit.DAYS));
    }

    /**
     * Echoes the window the response was computed for (default {@code 30}).
     */
    public static String normalizePublicStatsDays(String days) {
        String normalized = (days == null || days.isBlank()) ? "30" : days.trim().toLowerCase();
        if (!PUBLIC_STATS_DAY_OPTIONS.contains(normalized)) {
            throw new IllegalArgumentException(
                "days must be one of 7, 30, 90, 365, or all");
        }
        return normalized;
    }

    /**
     * Figures for the public stats page — the one part of the platform
     * reachable without a credential.
     *
     * <p>Scope decision (totals stay consistent with what is shown): every
     * aggregate is limited to teams with {@code show_on_public_stats = true}.
     * Non-selected teams never appear by name, and their traffic is not
     * folded into {@code successful_requests}, the key-type or lane splits,
     * or the active-student count. {@code teams} is the count of opted-in
     * teams (including those with no traffic in the window). {@code students}
     * are distinct active users who made at least one successful request on
     * an opted-in team inside the window. Request figures count settled
     * successes only, ranged on {@code timestamp_request} when {@code since}
     * is set. {@code successful_requests} and the breakdowns include every
     * success on published teams (personal and application/service keys);
     * {@code average_requests_per_user} divides only the active-student
     * cohort's successes by {@code students}, so automated traffic does not
     * inflate the per-student figure.
     *
     * <p>All aggregates are read inside one repeatable-read transaction so a
     * concurrent success cannot make the headline and breakdown totals
     * disagree. Callers must go through the Spring proxy (as
     * {@code PublicStatsController} does) — a self-call would skip the
     * transaction boundary.
     */
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public Map<String, Object> publicStats(String days) {
        String window = normalizePublicStatsDays(days);
        Timestamp since = resolvePublicStatsSince(days);

        long students = logEntryRepository.countActiveStudentsOnPublicTeams(since);
        long studentRequests =
            logEntryRepository.countSuccessfulRequestsFromActiveStudentsOnPublicTeams(since);
        long teams = teamRepository.countByShowOnPublicStatsTrue();

        List<Map<String, Object>> requestsPerTeam = new ArrayList<>();
        long successfulRequests = 0;
        for (TeamRequestCountProjection row : logEntryRepository.countSuccessfulByTeam(since)) {
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
        for (KeyTypeRequestCountProjection row : logEntryRepository.countSuccessfulByKeyType(since)) {
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
        for (ProviderTypeRequestCountProjection row : logEntryRepository.countSuccessfulByProviderType(since)) {
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

        double averageRequestsPerUser =
            students == 0 ? 0.0 : Math.round(studentRequests * 100.0 / students) / 100.0;

        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("days", window);
        stats.put("students", students);
        stats.put("teams", teams);
        stats.put("successful_requests", successfulRequests);
        stats.put("average_requests_per_user", averageRequestsPerUser);
        stats.put("requests_per_team", requestsPerTeam);
        stats.put("requests_by_key_type", requestsByKeyType);
        stats.put("local_cloud_requests", localCloud);

        // Distributions, shares and monthly series come from one row set
        // (day x team x user x lane x model), read from log_entry on the same
        // predicate as the headline totals above, so they describe the same
        // requests. The monthly series and first-session marker ignore the
        // window, hence the all-time read.
        List<PublicUsageRowProjection> allRows = logEntryRepository.findPublicUsageRows(null);
        List<PublicUsageRowProjection> windowRows =
            since == null ? allRows : logEntryRepository.findPublicUsageRows(since);
        List<AgentSessionDayProjection> allAgentDays = logEntryRepository.findAgentSessionDays(null);
        List<AgentSessionDayProjection> windowAgentDays =
            since == null ? allAgentDays : logEntryRepository.findAgentSessionDays(since);
        LocalDate today = Instant.now().atZone(ZoneOffset.UTC).toLocalDate();
        PublicUsageSummary.putAll(stats, windowRows, allRows, windowAgentDays, allAgentDays, today);
        return stats;
    }
}
