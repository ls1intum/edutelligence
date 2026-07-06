package de.tum.cit.aet.logos.logoswebservice.operations.entity;

import java.time.Instant;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

@Entity
@Table(name = "ollama_provider_snapshots")
public class OllamaProviderSnapshot {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    private Integer providerId;
    private Instant snapshotTs;
    private Integer totalModelsLoaded;
    private Long totalVramUsedBytes;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(columnDefinition = "jsonb")
    private String loadedModels;

    private Boolean pollSuccess;
    private String errorMessage;
    private Long totalMemoryBytes;
    private Long freeMemoryBytes;
    private String snapshotSource;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(columnDefinition = "jsonb")
    private String schedulerSignals;

    public Integer getId() { return id; }
    public Integer getProviderId() { return providerId; }
    public Instant getSnapshotTs() { return snapshotTs; }
    public Integer getTotalModelsLoaded() { return totalModelsLoaded; }
    public Long getTotalVramUsedBytes() { return totalVramUsedBytes; }
    public String getLoadedModels() { return loadedModels; }
    public Boolean getPollSuccess() { return pollSuccess; }
    public String getErrorMessage() { return errorMessage; }
    public Long getTotalMemoryBytes() { return totalMemoryBytes; }
    public Long getFreeMemoryBytes() { return freeMemoryBytes; }
    public String getSnapshotSource() { return snapshotSource; }
    public String getSchedulerSignals() { return schedulerSignals; }
}
