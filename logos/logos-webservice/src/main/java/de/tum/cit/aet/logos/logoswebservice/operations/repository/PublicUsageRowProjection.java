package de.tum.cit.aet.logos.logoswebservice.operations.repository;

/** One day of successful usage on an opted-in team, for the public stats page. */
public interface PublicUsageRowProjection {
    /** UTC day of {@code timestamp_request}, {@code YYYY-MM-DD}. */
    String getDay();
    /** Whether the requests fall inside the selected window. */
    Boolean getInWindow();
    Integer getTeamId();
    String getTeamName();
    /** The team's public category; null when uncategorized. */
    String getCategory();
    /** Null for application and service keys. */
    Integer getUserId();
    Boolean getStudent();
    /** {@code developer}, {@code application}, {@code service} or {@code unknown}. */
    String getKeyType();
    /** {@code local}, {@code cloud} or {@code unknown}. */
    String getLane();
    String getModel();
    Long getRequests();
    Long getTokens();
}
