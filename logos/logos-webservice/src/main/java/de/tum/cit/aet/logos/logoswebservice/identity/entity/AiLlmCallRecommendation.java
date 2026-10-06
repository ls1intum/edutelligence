package de.tum.cit.aet.logos.logoswebservice.identity.entity;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "ai_llm_call_recommendations")
public class AiLlmCallRecommendation {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(nullable = false)
    private Integer analysisId;

    private Integer workflowId;

    private Integer stepId;

    @Column(nullable = false)
    private Integer teamId;

    @Column(nullable = false)
    private String filePath;

    private Integer startLine;
    private Integer endLine;
    private String codeUrl;
    private String detectedModel;
    private Integer apiKeyId;

    @Column(nullable = false)
    private String recommendedSla;

    @Column(nullable = false)
    private Float confidence = 0.5f;

    @Column(nullable = false)
    private String justification = "";

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(columnDefinition = "jsonb")
    private Map<String, Object> trafficFlags;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "objective_priority", columnDefinition = "jsonb", nullable = false)
    private List<Object> objectivePriority = List.of("latency", "quality", "price");

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "confirmed_objective_priority", columnDefinition = "jsonb")
    private List<Object> confirmedObjectivePriority;

    @Column(nullable = false)
    private String reviewStatus = "pending";

    private String confirmedSla;
    private Integer reviewedBy;
    private Instant reviewedAt;
    /** The recommendation this one succeeds in the previous analysis of the same repository. */
    private Integer previousRecommendationId;
    /** The owner picked {@link #detectedModel}; the next analysis keeps it. */
    @Column(nullable = false)
    private boolean modelSetByOwner;
    /** The review was copied from an earlier decision by a re-analysis, not made on this row. */
    @Column(nullable = false)
    private boolean reviewCarriedOver;

    public Integer getId() { return id; }
    public Integer getAnalysisId() { return analysisId; }
    public Integer getWorkflowId() { return workflowId; }
    public Integer getStepId() { return stepId; }
    public Integer getTeamId() { return teamId; }
    public String getFilePath() { return filePath; }
    public Integer getStartLine() { return startLine; }
    public Integer getEndLine() { return endLine; }
    public String getCodeUrl() { return codeUrl; }
    public String getDetectedModel() { return detectedModel; }
    public Integer getApiKeyId() { return apiKeyId; }
    public String getRecommendedSla() { return recommendedSla; }
    public Float getConfidence() { return confidence; }
    public String getJustification() { return justification; }
    public Map<String, Object> getTrafficFlags() { return trafficFlags; }
    public List<Object> getObjectivePriority() { return objectivePriority; }
    public List<Object> getConfirmedObjectivePriority() { return confirmedObjectivePriority; }
    public String getReviewStatus() { return reviewStatus; }
    public String getConfirmedSla() { return confirmedSla; }
    public Integer getReviewedBy() { return reviewedBy; }
    public Instant getReviewedAt() { return reviewedAt; }
    public Integer getPreviousRecommendationId() { return previousRecommendationId; }
    public boolean isModelSetByOwner() { return modelSetByOwner; }
    public boolean isReviewCarriedOver() { return reviewCarriedOver; }

    public void setAnalysisId(Integer analysisId) { this.analysisId = analysisId; }
    public void setWorkflowId(Integer workflowId) { this.workflowId = workflowId; }
    public void setStepId(Integer stepId) { this.stepId = stepId; }
    public void setTeamId(Integer teamId) { this.teamId = teamId; }
    public void setFilePath(String filePath) { this.filePath = filePath; }
    public void setStartLine(Integer startLine) { this.startLine = startLine; }
    public void setEndLine(Integer endLine) { this.endLine = endLine; }
    public void setCodeUrl(String codeUrl) { this.codeUrl = codeUrl; }
    public void setDetectedModel(String detectedModel) { this.detectedModel = detectedModel; }
    public void setApiKeyId(Integer apiKeyId) { this.apiKeyId = apiKeyId; }
    public void setRecommendedSla(String recommendedSla) { this.recommendedSla = recommendedSla; }
    public void setConfidence(Float confidence) { this.confidence = confidence; }
    public void setJustification(String justification) { this.justification = justification; }
    public void setTrafficFlags(Map<String, Object> trafficFlags) { this.trafficFlags = trafficFlags; }
    public void setObjectivePriority(List<Object> objectivePriority) { this.objectivePriority = objectivePriority; }
    public void setConfirmedObjectivePriority(List<Object> confirmedObjectivePriority) {
        this.confirmedObjectivePriority = confirmedObjectivePriority;
    }
    public void setReviewStatus(String reviewStatus) { this.reviewStatus = reviewStatus; }
    public void setConfirmedSla(String confirmedSla) { this.confirmedSla = confirmedSla; }
    public void setReviewedBy(Integer reviewedBy) { this.reviewedBy = reviewedBy; }
    public void setReviewedAt(Instant reviewedAt) { this.reviewedAt = reviewedAt; }
    public void setPreviousRecommendationId(Integer previousRecommendationId) {
        this.previousRecommendationId = previousRecommendationId;
    }
    public void setModelSetByOwner(boolean modelSetByOwner) { this.modelSetByOwner = modelSetByOwner; }
    public void setReviewCarriedOver(boolean reviewCarriedOver) { this.reviewCarriedOver = reviewCarriedOver; }
}
