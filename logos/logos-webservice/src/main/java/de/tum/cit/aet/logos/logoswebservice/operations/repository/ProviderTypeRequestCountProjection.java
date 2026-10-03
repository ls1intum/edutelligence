package de.tum.cit.aet.logos.logoswebservice.operations.repository;

/**
 * Successful requests by provider type — the public stats page's local
 * (logosnode) vs. cloud split.
 */
public interface ProviderTypeRequestCountProjection {
    String getProviderType();
    Long getRequests();
}
