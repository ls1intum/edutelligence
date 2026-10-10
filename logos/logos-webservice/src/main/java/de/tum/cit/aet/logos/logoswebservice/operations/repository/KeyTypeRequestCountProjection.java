package de.tum.cit.aet.logos.logoswebservice.operations.repository;

/**
 * Successful requests by API key type — the public stats page's split
 * between members' personal (developer) keys and application keys.
 */
public interface KeyTypeRequestCountProjection {
    String getKeyType();
    Long getRequests();
}
