package de.tum.cit.aet.logos.logoswebservice.operations.repository;

/** Logos Agent sessions one person started on one UTC day. */
public interface AgentSessionDayProjection {
    /** UTC day, {@code YYYY-MM-DD}. */
    String getDay();
    Long getSessions();
    Long getSucceeded();
    Long getPullRequests();
    /** Hash of the starter, only used to count distinct people. */
    String getStarter();
}
