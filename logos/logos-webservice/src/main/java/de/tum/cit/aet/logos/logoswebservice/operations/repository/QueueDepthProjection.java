package de.tum.cit.aet.logos.logoswebservice.operations.repository;

public interface QueueDepthProjection {
    Double getAvgEnqueue();
    Double getAvgSchedule();
    Double getP95Enqueue();
    Double getP95Schedule();
}
