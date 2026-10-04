package de.tum.cit.aet.logos.logoswebservice.identity.repository;

public interface RateLimitUsageProjection {
    Integer getKeyId();
    Long getCloudRequests();
    Long getCloudTokens();
    Long getLocalRequests();
    Long getLocalTokens();
}
