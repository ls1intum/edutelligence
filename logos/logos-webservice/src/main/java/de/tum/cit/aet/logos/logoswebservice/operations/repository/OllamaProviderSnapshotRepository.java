package de.tum.cit.aet.logos.logoswebservice.operations.repository;

import java.time.Instant;
import java.util.Collection;
import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.operations.entity.OllamaProviderSnapshot;

public interface OllamaProviderSnapshotRepository extends JpaRepository<OllamaProviderSnapshot, Integer> {

    /**
     * Downsamples snapshots in the database: keeps only the latest snapshot id
     * per provider and time bucket ('minute' for single-day views, 'hour' for
     * all-time views) so the service never materializes every poll of a day.
     */
    @Transactional(readOnly = true)
    @Query("""
        SELECT MAX(s.id)
        FROM OllamaProviderSnapshot s
        WHERE s.pollSuccess = TRUE
          AND s.snapshotTs >= :startTs
          AND s.snapshotTs < :endTs
          AND s.id > :afterSnapshotId
        GROUP BY s.providerId, FUNCTION('date_trunc', :bucket, s.snapshotTs)
        """)
    List<Integer> findSampledSnapshotIds(
        @Param("startTs") Instant startTs,
        @Param("endTs") Instant endTs,
        @Param("afterSnapshotId") int afterSnapshotId,
        @Param("bucket") String bucket);

    @Transactional(readOnly = true)
    @Query("""
        SELECT s.id AS id,
               s.providerId AS providerId,
               p.name AS providerName,
               s.snapshotTs AS snapshotTs,
               s.totalVramUsedBytes AS totalVramUsedBytes,
               s.totalMemoryBytes AS totalMemoryBytes,
               s.freeMemoryBytes AS freeMemoryBytes,
               s.totalModelsLoaded AS totalModelsLoaded,
               s.loadedModels AS loadedModels,
               s.schedulerSignals AS schedulerSignals,
               p.totalVramMb AS totalVramMb
        FROM OllamaProviderSnapshot s
        LEFT JOIN Provider p ON p.id = s.providerId
        WHERE s.id IN :ids
        ORDER BY s.providerId, s.snapshotTs
        """)
    List<VramSnapshotProjection> findSnapshotsByIds(@Param("ids") Collection<Integer> ids);

    @Transactional(readOnly = true)
    @Query("""
        SELECT s.providerId AS providerId,
               MAX(COALESCE(s.totalMemoryBytes, s.totalVramUsedBytes)) AS capacityBytes
        FROM OllamaProviderSnapshot s
        WHERE s.pollSuccess = TRUE
          AND s.snapshotTs >= :startTs
          AND s.snapshotTs < :endTs
          AND s.id > :afterSnapshotId
        GROUP BY s.providerId
        """)
    List<ProviderCapacityProjection> findProviderCapacities(
        @Param("startTs") Instant startTs,
        @Param("endTs") Instant endTs,
        @Param("afterSnapshotId") int afterSnapshotId);
}
