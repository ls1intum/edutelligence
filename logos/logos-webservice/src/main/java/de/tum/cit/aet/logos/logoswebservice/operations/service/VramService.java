package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Service;

import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.operations.repository.OllamaProviderSnapshotRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.VramSnapshotProjection;

@Service
public class VramService {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private final OllamaProviderSnapshotRepository snapshotRepository;

    public VramService(OllamaProviderSnapshotRepository snapshotRepository) {
        this.snapshotRepository = snapshotRepository;
    }

    public Map<String, Object> getVramStats(String day) {
        return getVramStats(day, 0);
    }

    public Map<String, Object> getVramStats(String day, int afterSnapshotId) {
        ZonedDateTime now = ZonedDateTime.now(ZoneOffset.UTC);
        boolean allDays = day == null || day.isBlank() || "all".equalsIgnoreCase(day.strip());

        java.sql.Timestamp startTs = null;
        java.sql.Timestamp endTs = null;

        if (!allDays) {
            LocalDate parsedDay = LocalDate.parse(day.strip());
            ZonedDateTime startDt = parsedDay.atStartOfDay(ZoneOffset.UTC);
            ZonedDateTime endDt   = startDt.plusDays(1);
            if (startDt.isAfter(now)) {
                throw new IllegalArgumentException("Requested day is in the future.");
            }
            if (endDt.isAfter(now)) endDt = now;
            startTs = java.sql.Timestamp.from(startDt.toInstant());
            endTs   = java.sql.Timestamp.from(endDt.toInstant());
        }

        List<VramSnapshotProjection> snapshots = snapshotRepository.findVramSnapshots(
            startTs, endTs, afterSnapshotId);

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
            Long capacityBytesVal = s.getCapacityBytes();
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

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("providers", new ArrayList<>(providersData.values()));
        result.put("last_snapshot_id", lastSnapshotId[0]);
        return result;
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
