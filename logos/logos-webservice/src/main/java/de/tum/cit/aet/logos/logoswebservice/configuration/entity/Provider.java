package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

import java.time.OffsetDateTime;

import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "providers")
public class Provider {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(nullable = false)
    private String name;

    @Column(name = "base_url", nullable = false)
    private String baseUrl;

    @Enumerated(EnumType.STRING)
    @JdbcTypeCode(SqlTypes.NAMED_ENUM)
    @Column(name = "provider_type", columnDefinition = "provider_type_enum")
    private ProviderType providerType = ProviderType.logosnode;

    @Enumerated(EnumType.STRING)
    @JdbcTypeCode(SqlTypes.NAMED_ENUM)
    @Column(name = "cloud_provider_type", columnDefinition = "cloud_provider_type_enum")
    private CloudProviderType cloudProviderType;

    @Enumerated(EnumType.STRING)
    @JdbcTypeCode(SqlTypes.NAMED_ENUM)
    @Column(name = "privacy_level", columnDefinition = "threshold_enum", nullable = false)
    private ThresholdLevel privacyLevel = ThresholdLevel.LOCAL;

    @Column(name = "auth_name", nullable = false)
    private String authName;

    @Column(name = "auth_format", nullable = false)
    private String authFormat;

    @Column(name = "api_key")
    private String apiKey;

    @Column(name = "ollama_admin_url")
    private String ollamaAdminUrl = "";

    @Column(name = "total_vram_mb")
    private Integer totalVramMb;

    @Column(name = "parallel_capacity")
    private Integer parallelCapacity = 20;

    @Column(name = "keep_alive_seconds")
    private Integer keepAliveSeconds = 300;

    @Column(name = "max_loaded_models")
    private Integer maxLoadedModels = 3;

    @Column(name = "updated_at")
    private OffsetDateTime updatedAt;

    public Integer getId() { return id; }
    public String getName() { return name; }
    public String getBaseUrl() { return baseUrl; }
    public ProviderType getProviderType() { return providerType; }
    public CloudProviderType getCloudProviderType() { return cloudProviderType; }
    public ThresholdLevel getPrivacyLevel() { return privacyLevel; }
    public String getAuthName() { return authName; }
    public String getAuthFormat() { return authFormat; }
    public String getApiKey() { return apiKey; }
    public String getOllamaAdminUrl() { return ollamaAdminUrl; }
    public Integer getTotalVramMb() { return totalVramMb; }
    public Integer getParallelCapacity() { return parallelCapacity; }
    public Integer getKeepAliveSeconds() { return keepAliveSeconds; }
    public Integer getMaxLoadedModels() { return maxLoadedModels; }
    public OffsetDateTime getUpdatedAt() { return updatedAt; }

    public void setName(String name) { this.name = name; }
    public void setBaseUrl(String baseUrl) { this.baseUrl = baseUrl; }
    public void setProviderType(ProviderType providerType) { this.providerType = providerType; }
    public void setCloudProviderType(CloudProviderType cloudProviderType) { this.cloudProviderType = cloudProviderType; }
    public void setPrivacyLevel(ThresholdLevel privacyLevel) { this.privacyLevel = privacyLevel; }
    public void setAuthName(String authName) { this.authName = authName; }
    public void setAuthFormat(String authFormat) { this.authFormat = authFormat; }
    public void setApiKey(String apiKey) { this.apiKey = apiKey; }
    public void setOllamaAdminUrl(String ollamaAdminUrl) { this.ollamaAdminUrl = ollamaAdminUrl; }
    public void setTotalVramMb(Integer totalVramMb) { this.totalVramMb = totalVramMb; }
    public void setParallelCapacity(Integer parallelCapacity) { this.parallelCapacity = parallelCapacity; }
    public void setKeepAliveSeconds(Integer keepAliveSeconds) { this.keepAliveSeconds = keepAliveSeconds; }
    public void setMaxLoadedModels(Integer maxLoadedModels) { this.maxLoadedModels = maxLoadedModels; }
    public void setUpdatedAt(OffsetDateTime updatedAt) { this.updatedAt = updatedAt; }
}
