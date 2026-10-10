package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

public interface PairLatencyStatsProjection {
    Long getSamples();
    Double getTotalP50Ms();
    Double getTtftP50Ms();
}
