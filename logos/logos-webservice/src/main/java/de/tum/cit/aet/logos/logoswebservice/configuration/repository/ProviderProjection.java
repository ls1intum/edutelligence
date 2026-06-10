package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

public interface ProviderProjection {
    Integer getId();
    String getName();
    String getBaseUrl();
    String getApiKey();
    String getProviderType();
    String getCloudProviderType();
    String getPrivacyLevel();
    String getAuthName();
    String getAuthFormat();
}
