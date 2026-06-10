package de.tum.cit.aet.logos.logoswebservice.operations.repository;

import java.time.Instant;

public interface LatestRequestProjection {
    String getRequestId();
    String getModelName();
    String getProviderName();
    String getResultStatus();
    Instant getTimestampRequest();
    Instant getTimestampForwarding();
    Instant getTimestampResponse();
    Boolean getWasColdStart();
    String getInitialPriority();
    String getPriorityWhenScheduled();
    Integer getQueueDepthAtEnqueue();
    String getErrorMessage();
    Double getRunSeconds();
    Double getQueueSeconds();
    Double getTotalSeconds();
}
