package de.tum.cit.aet.logos.logoswebservice.operations.repository;

/**
 * One team's share of the platform's successful requests — a slice of the
 * public stats page's per-team pie. A null team id is a real group:
 * successful requests whose key recorded no team.
 */
public interface TeamRequestCountProjection {
    Integer getTeamId();
    String getTeamName();
    Long getRequests();
}
