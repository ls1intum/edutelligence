package de.tum.cit.aet.logos.logoswebservice.operations.repository;

public interface RequestLogTotalsProjection {
    Long getRequests();
    Long getCloudRequests();
    Long getLocalRequests();
    Long getColdStarts();
    Long getWarmStarts();
    Double getAvgQueueSeconds();
    Double getAvgRunSeconds();
}
