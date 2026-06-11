package de.tum.cit.aet.logos.logoswebservice.operations.repository;

import java.time.Instant;

public interface PaginatedRequestProjection {
    String getRequestId();
    String getModelName();
    String getProviderName();
    String getProviderType();
    String getResultStatus();
    Instant getEnqueueTs();
    Instant getScheduledTs();
    Instant getRequestCompleteTs();
    Double getRunSeconds();
    Double getQueueSeconds();
    Double getTotalSeconds();
    Boolean getColdStart();
    String getInitialPriority();
    String getPriorityWhenScheduled();
    Integer getQueueDepthAtEnqueue();
    String getErrorMessage();
}
