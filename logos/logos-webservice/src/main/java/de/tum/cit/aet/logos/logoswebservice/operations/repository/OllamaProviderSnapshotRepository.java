package de.tum.cit.aet.logos.logoswebservice.operations.repository;

import java.sql.Timestamp;
import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.operations.entity.OllamaProviderSnapshot;

public interface OllamaProviderSnapshotRepository extends JpaRepository<OllamaProviderSnapshot, Integer> {

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT s.id AS id,
               s.provider_id AS providerId,
               p.name AS providerName,
               s.snapshot_ts AS snapshotTs,
               s.total_vram_used_bytes AS totalVramUsedBytes,
               s.total_memory_bytes AS totalMemoryBytes,
               s.free_memory_bytes AS freeMemoryBytes,
               s.total_models_loaded AS totalModelsLoaded,
               s.loaded_models::text AS loadedModels,
               s.scheduler_signals::text AS schedulerSignals,
               p.total_vram_mb AS totalVramMb,
               MAX(COALESCE(s.total_memory_bytes, s.total_vram_used_bytes))
                   OVER (PARTITION BY s.provider_id) AS capacityBytes
        FROM ollama_provider_snapshots s
        LEFT JOIN providers p ON p.id = s.provider_id
        WHERE s.poll_success = TRUE
          AND s.snapshot_ts >= COALESCE(CAST(:startTs AS timestamptz), '-infinity'::timestamptz)
          AND s.snapshot_ts < COALESCE(CAST(:endTs AS timestamptz), 'infinity'::timestamptz)
          AND (:afterSnapshotId = 0 OR s.id > :afterSnapshotId)
        ORDER BY s.provider_id, s.snapshot_ts
        """, nativeQuery = true)
    List<VramSnapshotProjection> findVramSnapshots(
        @Param("startTs") Timestamp startTs,
        @Param("endTs") Timestamp endTs,
        @Param("afterSnapshotId") int afterSnapshotId);
}
