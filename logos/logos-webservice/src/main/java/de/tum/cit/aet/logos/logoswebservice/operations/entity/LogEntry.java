package de.tum.cit.aet.logos.logoswebservice.operations.entity;

import java.time.Instant;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.LogLevel;

@Entity
@Table(name = "log_entry")
public class LogEntry {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(nullable = false)
    private Instant timestampRequest;

    private Instant timestampForwarding;
    private Instant timestampResponse;
    private Instant timeAtFirstToken;

    @Enumerated(EnumType.STRING)
    @JdbcTypeCode(SqlTypes.NAMED_ENUM)
    @Column(columnDefinition = "logging_enum")
    private LogLevel privacyLevel;

    private Integer providerId;
    private Integer modelId;
    private Integer policyId;
    private String requestId;
    private String priority;
    private String initialPriority;
    private String priorityWhenScheduled;
    private Integer queueDepthAtEnqueue;
    private Integer queueDepthAtSchedule;
    @Column(name = "timeout_s")
    private Integer timeoutS;
    private Integer queueDepthAtArrival;
    private Float utilizationAtArrival;
    private Float queueWaitMs;
    private Boolean wasColdStart;
    private Float loadDurationMs;
    private Integer availableVramMb;
    private Integer azureRateRemainingRequests;
    private Integer azureRateRemainingTokens;

    @Enumerated(EnumType.STRING)
    @JdbcTypeCode(SqlTypes.NAMED_ENUM)
    @Column(columnDefinition = "result_status_enum")
    private ResultStatus resultStatus;

    private String errorMessage;
    private Integer apiKeyId;
    private Integer teamId;
    private Integer userId;
    private String environment;

    public Integer getId() { return id; }
    public Instant getTimestampRequest() { return timestampRequest; }
    public Instant getTimestampForwarding() { return timestampForwarding; }
    public Instant getTimestampResponse() { return timestampResponse; }
    public Instant getTimeAtFirstToken() { return timeAtFirstToken; }
    public LogLevel getPrivacyLevel() { return privacyLevel; }
    public Integer getProviderId() { return providerId; }
    public Integer getModelId() { return modelId; }
    public Integer getPolicyId() { return policyId; }
    public String getRequestId() { return requestId; }
    public String getPriority() { return priority; }
    public String getInitialPriority() { return initialPriority; }
    public String getPriorityWhenScheduled() { return priorityWhenScheduled; }
    public Integer getQueueDepthAtEnqueue() { return queueDepthAtEnqueue; }
    public Integer getQueueDepthAtSchedule() { return queueDepthAtSchedule; }
    public Integer getTimeoutS() { return timeoutS; }
    public Integer getQueueDepthAtArrival() { return queueDepthAtArrival; }
    public Float getUtilizationAtArrival() { return utilizationAtArrival; }
    public Float getQueueWaitMs() { return queueWaitMs; }
    public Boolean getWasColdStart() { return wasColdStart; }
    public Float getLoadDurationMs() { return loadDurationMs; }
    public Integer getAvailableVramMb() { return availableVramMb; }
    public Integer getAzureRateRemainingRequests() { return azureRateRemainingRequests; }
    public Integer getAzureRateRemainingTokens() { return azureRateRemainingTokens; }
    public ResultStatus getResultStatus() { return resultStatus; }
    public String getErrorMessage() { return errorMessage; }
    public Integer getApiKeyId() { return apiKeyId; }
    public Integer getTeamId() { return teamId; }
    public Integer getUserId() { return userId; }
    public String getEnvironment() { return environment; }
}
