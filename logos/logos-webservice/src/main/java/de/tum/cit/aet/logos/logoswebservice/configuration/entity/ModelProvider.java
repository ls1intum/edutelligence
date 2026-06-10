package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

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

    public Integer getId() { return id; }
    public Integer getProviderId() { return providerId; }
    public Integer getModelId() { return modelId; }
    public String getApiKey() { return apiKey; }
    public String getEndpoint() { return endpoint; }

    public void setProviderId(Integer providerId) { this.providerId = providerId; }
    public void setModelId(Integer modelId) { this.modelId = modelId; }
    public void setApiKey(String apiKey) { this.apiKey = apiKey; }
    public void setEndpoint(String endpoint) { this.endpoint = endpoint; }
}
