package de.tum.cit.aet.logos.logoswebservice.operations.repository;

import java.time.Instant;

public interface RequestLogProjection {
    String getRequestId();
    String getModelName();
    String getProviderName();
    String getResultStatus();
    Instant getEnqueueTs();
    Instant getScheduledTs();
    Instant getRequestCompleteTs();
    Double getTtftMs();
    Double getTotalLatencyMs();
    Double getQueueWaitMs();
    Double getProcessingMs();
    Boolean getColdStart();
    Integer getQueueDepthAtArrival();
    Float getUtilizationAtArrival();
    Integer getQueueDepthAtSchedule();
    String getPriorityWhenScheduled();
    Float getLoadDurationMs();
    Integer getAvailableVramMb();
    Integer getAzureRateRemainingRequests();
    Integer getAzureRateRemainingTokens();
    String getErrorMessage();
    Long getPromptTokens();
    Long getCompletionTokens();
    Long getTotalTokens();
}
