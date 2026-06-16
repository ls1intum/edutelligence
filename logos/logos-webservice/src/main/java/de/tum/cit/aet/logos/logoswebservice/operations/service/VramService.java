package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Service;

import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.operations.repository.OllamaProviderSnapshotRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.ProviderCapacityProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.VramSnapshotProjection;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorStatusClient;

@Service
public class VramService {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private final OllamaProviderSnapshotRepository snapshotRepository;
    private final OrchestratorStatusClient orchestratorStatusClient;

    public VramService(OllamaProviderSnapshotRepository snapshotRepository,
                       OrchestratorStatusClient orchestratorStatusClient) {
        this.snapshotRepository = snapshotRepository;
        this.orchestratorStatusClient = orchestratorStatusClient;
    }

    public Map<String, Object> getVramStats(String day) {
        return getVramStats(day, 0);
    }

    public Map<String, Object> getVramStats(String day, int afterSnapshotId) {
        return getVramStats(day, afterSnapshotId, null);
    }

    /**
     * @param resolution {@code null} for the default downsampling (latest
     *                   snapshot per provider per minute, per hour for the
     *                   all-days view) or {@code "second"} to keep every
     *                   stored snapshot (latest per second) — used by
     *                   benchmark tooling that needs at least 1 Hz data.
     */
    public Map<String, Object> getVramStats(String day, int afterSnapshotId, String resolution) {
        ZonedDateTime now = ZonedDateTime.now(ZoneOffset.UTC);
        boolean allDays = day == null || day.isBlank() || "all".equalsIgnoreCase(day.strip());

        Instant startTs = Instant.EPOCH;
        Instant endTs = now.toInstant();

        if (!allDays) {
            LocalDate parsedDay = LocalDate.parse(day.strip());
            ZonedDateTime startDt = parsedDay.atStartOfDay(ZoneOffset.UTC);
            ZonedDateTime endDt   = startDt.plusDays(1);
            if (startDt.isAfter(now)) {
                throw new IllegalArgumentException("Requested day is in the future.");
            }
            if (endDt.isAfter(now)) endDt = now;
            startTs = startDt.toInstant();
            endTs   = endDt.toInstant();
        }

        // Downsample in the DB: latest snapshot per provider per minute for a
        // single day, per hour for the unbounded all-days view. With
        // resolution=second the bucket collapses to the raw snapshot cadence.
        String bucket = resolveBucket(resolution, allDays);
        List<Integer> sampledIds = snapshotRepository.findSampledSnapshotIds(
            startTs, endTs, afterSnapshotId, bucket);

        Map<String, Object> result = new LinkedHashMap<>();
        if (sampledIds.isEmpty()) {
            result.put("providers", enrichProviders(new LinkedHashMap<>()));
            result.put("last_snapshot_id", afterSnapshotId);
            return result;
        }

        Map<Integer, Long> capacities = new HashMap<>();
        for (ProviderCapacityProjection c : snapshotRepository.findProviderCapacities(
                startTs, endTs, afterSnapshotId)) {
            if (c.getCapacityBytes() != null) capacities.put(c.getProviderId(), c.getCapacityBytes());
        }

        List<VramSnapshotProjection> snapshots = snapshotRepository.findSnapshotsByIds(sampledIds);

        Map<Integer, Map<String, Object>> providersData = new LinkedHashMap<>();
        int[] lastSnapshotId = {afterSnapshotId};

        for (VramSnapshotProjection s : snapshots) {
            int pid = s.getProviderId();
            String rawName = s.getProviderName();
            String providerName = rawName != null ? rawName : "Provider " + pid;

            int snapshotId = s.getId();
            if (snapshotId > lastSnapshotId[0]) lastSnapshotId[0] = snapshotId;

            long usedBytes = s.getTotalVramUsedBytes() != null ? s.getTotalVramUsedBytes() : 0L;
            Long totalMemBytesVal = s.getTotalMemoryBytes();
            long totalMemBytes = totalMemBytesVal != null ? totalMemBytesVal : 0L;
            Long freeBytesVal = s.getFreeMemoryBytes();
            boolean freeNull = freeBytesVal == null;
            long freeBytes = freeNull ? 0L : freeBytesVal;
            Integer totalVramMbVal = s.getTotalVramMb();
            long configuredBytes = totalVramMbVal != null ? (long) totalVramMbVal * 1024L * 1024L : 0L;
            Long capacityBytesVal = capacities.get(pid);
            long capacityBytes = capacityBytesVal != null ? capacityBytesVal : 0L;
            long cap = totalMemBytes > 0 ? totalMemBytes
                     : configuredBytes > 0 ? configuredBytes
                     : capacityBytes > 0 ? capacityBytes
                     : usedBytes;
            long remaining = freeNull ? Math.max(cap - usedBytes, 0) : freeBytes;

            Map<String, Object> sample = new LinkedHashMap<>();
            sample.put("snapshot_id", snapshotId);
            sample.put("timestamp", ts(s.getSnapshotTs()));
            sample.put("vram_mb", usedBytes / (1024 * 1024));
            sample.put("vram_bytes", usedBytes);
            sample.put("used_vram_mb", usedBytes / (1024 * 1024));
            sample.put("remaining_vram_mb", remaining / (1024 * 1024));
            sample.put("total_vram_mb", cap > 0 ? cap / (1024 * 1024) : null);
            sample.put("models_loaded", s.getTotalModelsLoaded());
            sample.put("loaded_models", parseJson(s.getLoadedModels()));
            sample.put("scheduler_signals", parseJsonOrEmpty(s.getSchedulerSignals()));

            providersData.computeIfAbsent(pid, id -> {
                Map<String, Object> p = new LinkedHashMap<>();
                p.put("provider_id", id);
                p.put("name", providerName);
                p.put("data", new ArrayList<>());
                return p;
            });
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> data =
                    (List<Map<String, Object>>) providersData.get(pid).get("data");
            data.add(sample);
        }

        result.put("providers", enrichProviders(providersData));
        result.put("last_snapshot_id", lastSnapshotId[0]);
        return result;
    }

    private static String resolveBucket(String resolution, boolean allDays) {
        String normalized = resolution != null ? resolution.strip().toLowerCase() : "";
        return switch (normalized) {
            case "", "default" -> allDays ? "hour" : "minute";
            case "second", "raw" -> "second";
            case "minute" -> "minute";
            case "hour" -> "hour";
            default -> throw new IllegalArgumentException(
                "Unsupported resolution '" + resolution + "' (use second, minute or hour).");
        };
    }

    /**
     * Attaches live connection metadata (connected/connection_state/
     * last_heartbeat) from the orchestrator's worker registry and adds
     * configured providers without snapshots in range, so offline providers
     * still show up — and show up as offline — on the statistics page.
     */
    private List<Map<String, Object>> enrichProviders(Map<Integer, Map<String, Object>> providersData) {
        Map<Integer, Map<String, Object>> statusById = orchestratorStatusClient.getProviderStatusById();
        for (Map.Entry<Integer, Map<String, Object>> entry : statusById.entrySet()) {
            Map<String, Object> status = entry.getValue();
            Map<String, Object> provider = providersData.get(entry.getKey());
            if (provider == null) {
                provider = new LinkedHashMap<>();
                provider.put("provider_id", entry.getKey());
                provider.put("name", status.get("name") != null ? status.get("name") : "Provider " + entry.getKey());
                provider.put("data", new ArrayList<>());
                providersData.put(entry.getKey(), provider);
            }
            provider.put("provider_type", status.get("provider_type"));
            provider.put("connected", status.get("connected"));
            provider.put("connection_state", status.get("connection_state"));
            provider.put("last_heartbeat", status.get("last_heartbeat"));
        }
        return new ArrayList<>(providersData.values());
    }

    private static String ts(Instant t) {
        return t != null ? t.toString() : null;
    }

    private Object parseJson(String json) {
        if (json == null || json.isBlank()) return List.of();
        try { return OBJECT_MAPPER.readValue(json, Object.class); }
        catch (Exception e) { return List.of(); }
    }

    private Object parseJsonOrEmpty(String json) {
        if (json == null || json.isBlank()) return Map.of();
        try {
            Object parsed = OBJECT_MAPPER.readValue(json, Object.class);
            return parsed instanceof Map ? parsed : Map.of();
        } catch (Exception e) { return Map.of(); }
    }
}
