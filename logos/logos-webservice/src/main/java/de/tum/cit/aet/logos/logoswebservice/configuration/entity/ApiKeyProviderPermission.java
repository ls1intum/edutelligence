package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

import jakarta.persistence.EmbeddedId;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;

@Entity
@Table(name = "api_key_provider_permissions")
public class ApiKeyProviderPermission {
    @EmbeddedId
    private ApiKeyProviderPermissionId id;

    public ApiKeyProviderPermission() {}
    public ApiKeyProviderPermission(Integer apiKeyId, Integer providerId) {
        this.id = new ApiKeyProviderPermissionId(apiKeyId, providerId);
    }

    public ApiKeyProviderPermissionId getId() { return id; }
    public void setId(ApiKeyProviderPermissionId id) { this.id = id; }
}
