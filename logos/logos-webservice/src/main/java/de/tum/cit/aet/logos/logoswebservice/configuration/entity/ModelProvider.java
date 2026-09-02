package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

import java.math.BigDecimal;
import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;

@Entity
@Table(name = "model_provider",
       uniqueConstraints = @UniqueConstraint(columnNames = {"model_id", "provider_id"}))
public class ModelProvider {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(nullable = false)
    private Integer providerId;

    @Column(nullable = false)
    private Integer modelId;

    private String apiKey;
    private String endpoint;

    // Auto-derived L/A/C/Q metrics for this model-provider pair. The unit of
    // derivedCostUsd depends on the provider type: USD per million tokens for
    // cloud pairs (catalogue blend), USD per request for local pairs
    // (VRAM x latency proxy). Only the cloud unit is commensurable across
    // pairs, so the model-level cost ranking uses cloud pairs only.
    // Populated by ModelMetricsService; NULL until enough data has been observed.
    private Integer derivedTtftMs;
    private Integer derivedTotalLatencyMs;
    private Integer derivedTpotMs;
    private BigDecimal derivedCostUsd;
    private Integer derivedSamples = 0;
    private Instant derivedUpdatedAt;

    public Integer getId() { return id; }
    public Integer getProviderId() { return providerId; }
    public Integer getModelId() { return modelId; }
    public String getApiKey() { return apiKey; }
    public String getEndpoint() { return endpoint; }
    public Integer getDerivedTtftMs() { return derivedTtftMs; }
    public Integer getDerivedTotalLatencyMs() { return derivedTotalLatencyMs; }
    public Integer getDerivedTpotMs() { return derivedTpotMs; }
    public BigDecimal getDerivedCostUsd() { return derivedCostUsd; }
    public Integer getDerivedSamples() { return derivedSamples; }
    public Instant getDerivedUpdatedAt() { return derivedUpdatedAt; }

    public void setProviderId(Integer providerId) { this.providerId = providerId; }
    public void setModelId(Integer modelId) { this.modelId = modelId; }
    public void setApiKey(String apiKey) { this.apiKey = apiKey; }
    public void setEndpoint(String endpoint) { this.endpoint = endpoint; }
    public void setDerivedTtftMs(Integer derivedTtftMs) { this.derivedTtftMs = derivedTtftMs; }
    public void setDerivedTotalLatencyMs(Integer derivedTotalLatencyMs) { this.derivedTotalLatencyMs = derivedTotalLatencyMs; }
    public void setDerivedTpotMs(Integer derivedTpotMs) { this.derivedTpotMs = derivedTpotMs; }
    public void setDerivedCostUsd(BigDecimal derivedCostUsd) { this.derivedCostUsd = derivedCostUsd; }
    public void setDerivedSamples(Integer derivedSamples) { this.derivedSamples = derivedSamples; }
    public void setDerivedUpdatedAt(Instant derivedUpdatedAt) { this.derivedUpdatedAt = derivedUpdatedAt; }
}
