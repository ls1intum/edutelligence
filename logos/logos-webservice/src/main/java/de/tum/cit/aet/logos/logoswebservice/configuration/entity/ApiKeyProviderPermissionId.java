package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

import java.io.Serializable;
import java.util.Objects;
import jakarta.persistence.Embeddable;

@Embeddable
public class ApiKeyProviderPermissionId implements Serializable {
    private Integer apiKeyId;
    private Integer providerId;

    public ApiKeyProviderPermissionId() {}
    public ApiKeyProviderPermissionId(Integer apiKeyId, Integer providerId) {
        this.apiKeyId = apiKeyId;
        this.providerId = providerId;
    }

    public Integer getApiKeyId() { return apiKeyId; }
    public Integer getProviderId() { return providerId; }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof ApiKeyProviderPermissionId that)) return false;
        return Objects.equals(apiKeyId, that.apiKeyId) && Objects.equals(providerId, that.providerId);
    }
    @Override public int hashCode() { return Objects.hash(apiKeyId, providerId); }
}
