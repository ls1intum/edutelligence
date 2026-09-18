package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.time.Instant;

public interface ModelHostingProviderProjection {
    Integer getProviderId();
    String getName();
    String getProviderType();
    String getPrivacyLevel();
    Long getRequestCount();
    Instant getLastRequestAt();
}
