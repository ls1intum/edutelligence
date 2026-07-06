package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

import java.io.Serializable;
import java.util.Objects;
import jakarta.persistence.Embeddable;

@Embeddable
public class ApiKeyModelPermissionId implements Serializable {
    private Integer apiKeyId;
    private Integer modelId;

    public ApiKeyModelPermissionId() {}
    public ApiKeyModelPermissionId(Integer apiKeyId, Integer modelId) {
        this.apiKeyId = apiKeyId;
        this.modelId = modelId;
    }

    public Integer getApiKeyId() { return apiKeyId; }
    public Integer getModelId() { return modelId; }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof ApiKeyModelPermissionId that)) return false;
        return Objects.equals(apiKeyId, that.apiKeyId) && Objects.equals(modelId, that.modelId);
    }
    @Override public int hashCode() { return Objects.hash(apiKeyId, modelId); }
}
