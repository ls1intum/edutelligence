package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.sql.Timestamp;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import com.fasterxml.jackson.databind.ObjectMapper;

@Service
public class VramService {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private final JdbcTemplate jdbcTemplate;

    public VramService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public Map<String, Object> getVramStats(String day) {
        return getVramStats(day, 0);
    }

    public Map<String, Object> getVramStats(String day, long afterSnapshotId) {
        ZonedDateTime now = ZonedDateTime.now(ZoneOffset.UTC);
        boolean allDays = day == null || day.isBlank() || "all".equalsIgnoreCase(day.strip());

        List<Object> argsList = new ArrayList<>();
        StringBuilder where = new StringBuilder("WHERE s.poll_success = TRUE");

        if (!allDays) {
            LocalDate parsedDay = LocalDate.parse(day.strip());
            ZonedDateTime startDt = parsedDay.atStartOfDay(ZoneOffset.UTC);
            ZonedDateTime endDt   = startDt.plusDays(1);
            if (startDt.isAfter(now)) {
                throw new IllegalArgumentException("Requested day is in the future.");
            }
            if (endDt.isAfter(now)) endDt = now;
            where.append("\n  AND s.snapshot_ts >= ?");
            argsList.add(Timestamp.from(startDt.toInstant()));
            where.append("\n  AND s.snapshot_ts < ?");
            argsList.add(Timestamp.from(endDt.toInstant()));
        }

        if (afterSnapshotId > 0) {
            where.append("\n  AND s.id > ?");
            argsList.add(afterSnapshotId);
        }

        Map<Integer, Map<String, Object>> providersData = new LinkedHashMap<>();
        long[] lastSnapshotId = {afterSnapshotId};

        String sql = """
            SELECT s.id,
                   s.provider_id,
                   p.name AS provider_name,
                   s.snapshot_ts,
                   s.total_vram_used_bytes,
                   s.total_memory_bytes,
                   s.free_memory_bytes,
                   s.total_models_loaded,
                   s.loaded_models::text AS loaded_models,
                   s.scheduler_signals::text AS scheduler_signals,
                   p.total_vram_mb,
                   MAX(COALESCE(s.total_memory_bytes, s.total_vram_used_bytes))
                       OVER (PARTITION BY s.provider_id) AS capacity_bytes
            FROM ollama_provider_snapshots s
            LEFT JOIN providers p ON p.id = s.provider_id
            """ + where + """

            ORDER BY s.provider_id, s.snapshot_ts
            """;

        Object[] args = argsList.toArray();

        jdbcTemplate.query(sql, rs -> {
                int pid = rs.getInt("provider_id");
                String rawName = rs.getString("provider_name");
                String providerName = rawName != null ? rawName : "Provider " + pid;

                long snapshotId = rs.getLong("id");
                if (snapshotId > lastSnapshotId[0]) lastSnapshotId[0] = snapshotId;

                long usedBytes = rs.getLong("total_vram_used_bytes");
                long totalMemBytes  = rs.getLong("total_memory_bytes");
                long freeBytes = rs.getLong("free_memory_bytes");
                boolean freeNull = rs.wasNull();
                long configuredBytes = rs.getLong("total_vram_mb") * 1024L * 1024L;
                long capacityBytes  = rs.getLong("capacity_bytes");
                long cap = totalMemBytes > 0 ? totalMemBytes
                         : configuredBytes > 0 ? configuredBytes
                         : capacityBytes > 0 ? capacityBytes
                         : usedBytes;
                long remaining = freeNull ? Math.max(cap - usedBytes, 0) : freeBytes;

                String loadedModelsJson = rs.getString("loaded_models");
                String schedulerSignalsJson = rs.getString("scheduler_signals");

                Map<String, Object> sample = new LinkedHashMap<>();
                sample.put("snapshot_id", snapshotId);
                sample.put("timestamp", ts(rs.getTimestamp("snapshot_ts")));
                sample.put("vram_mb", usedBytes / (1024 * 1024));
                sample.put("vram_bytes", usedBytes);
                sample.put("used_vram_mb", usedBytes / (1024 * 1024));
                sample.put("remaining_vram_mb", remaining / (1024 * 1024));
                sample.put("total_vram_mb", cap > 0 ? cap / (1024 * 1024) : null);
                sample.put("models_loaded", rs.getInt("total_models_loaded"));
                sample.put("loaded_models", parseJson(loadedModelsJson));
                sample.put("scheduler_signals", parseJsonOrEmpty(schedulerSignalsJson));

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
            }, args);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("providers", new ArrayList<>(providersData.values()));
        result.put("last_snapshot_id", lastSnapshotId[0]);
        return result;
    }

    private static String ts(java.sql.Timestamp t) {
        return t != null ? t.toInstant().toString() : null;
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
