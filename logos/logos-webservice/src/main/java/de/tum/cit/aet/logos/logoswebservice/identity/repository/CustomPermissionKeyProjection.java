package de.tum.cit.aet.logos.logoswebservice.identity.repository;

/**
 * An API key with custom permissions that touches a model through a model
 * grant or a provider grant on one of the model's hosting providers.
 */
public interface CustomPermissionKeyProjection {
    Integer getKeyId();
    String getKeyName();
    Boolean getIsActive();
    Integer getTeamId();
    String getTeamName();
    Boolean getModelGrant();
}
