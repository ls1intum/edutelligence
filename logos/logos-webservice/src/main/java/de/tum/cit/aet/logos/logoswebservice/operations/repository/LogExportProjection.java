package de.tum.cit.aet.logos.logoswebservice.operations.repository;

import java.time.Instant;

/**
 * One consent-based (FULL) request trace for the team export (issue #667).
 *
 * The payload columns are selected as text: the database handshakes JSONB as
 * a string, and the service turns them back into objects before they go out,
 * so a trace reads as structured data in the download rather than a string
 * that happens to contain JSON.
 */
public interface LogExportProjection {
    Integer getId();
    String getRequestId();
    Instant getTimestampRequest();
    Instant getTimestampForwarding();
    Instant getTimestampResponse();
    Instant getTimeAtFirstToken();
    String getPrivacyLevel();
    String getModelName();
    String getProviderName();
    String getProviderType();
    Integer getPolicyId();
    String getEnvironment();
    Integer getApiKeyId();
    String getKeyName();
    String getUsername();
    String getFullName();
    String getTeamName();
    String getClientIp();
    String getResultStatus();
    String getErrorMessage();
    String getPriority();
    String getInitialPriority();
    String getPriorityWhenScheduled();
    Integer getQueueDepthAtEnqueue();
    Integer getQueueDepthAtSchedule();
    Integer getQueueDepthAtArrival();
    Integer getTimeoutS();
    Float getUtilizationAtArrival();
    Float getQueueWaitMs();
    Boolean getWasColdStart();
    Float getLoadDurationMs();
    Integer getAvailableVramMb();
    Integer getAzureRateRemainingRequests();
    Integer getAzureRateRemainingTokens();
    Long getPromptTokens();
    Long getCompletionTokens();
    Long getTotalTokens();
    Long getCostMicroCents();
    String getClassificationStatistics();
    String getInputPayload();
    String getHeaders();
    String getResponsePayload();
}
