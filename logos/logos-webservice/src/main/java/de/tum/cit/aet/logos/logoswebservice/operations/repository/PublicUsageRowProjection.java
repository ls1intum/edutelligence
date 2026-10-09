package de.tum.cit.aet.logos.logoswebservice.operations.repository;

/** One day of successful usage on an opted-in team, for the public stats page. */
public interface PublicUsageRowProjection {
    /** UTC day, {@code YYYY-MM-DD}. */
    String getDay();
    Integer getTeamId();
    /** The team's public category; null when uncategorized. */
    String getCategory();
    /** Null for application and service keys. */
    Integer getUserId();
    Boolean getStudent();
    /** {@code local}, {@code cloud} or {@code unknown}. */
    String getLane();
    String getModel();
    Long getRequests();
    Long getTokens();
}
