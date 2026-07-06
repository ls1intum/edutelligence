package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

import jakarta.persistence.EmbeddedId;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;

@Entity
@Table(name = "api_key_model_permissions")
public class ApiKeyModelPermission {
    @EmbeddedId
    private ApiKeyModelPermissionId id;

    public ApiKeyModelPermission() {}
    public ApiKeyModelPermission(Integer apiKeyId, Integer modelId) {
        this.id = new ApiKeyModelPermissionId(apiKeyId, modelId);
    }

    public ApiKeyModelPermissionId getId() { return id; }
    public void setId(ApiKeyModelPermissionId id) { this.id = id; }
}
