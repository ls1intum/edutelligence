package de.tum.cit.aet.logos.logoswebservice.identity.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "ai_workflows")
public class AiWorkflow {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(nullable = false)
    private Integer analysisId;

    @Column(nullable = false)
    private String name;

    private String triggerSummary;

    @Column(nullable = false)
    private String diagramMermaid = "";

    @Column(nullable = false)
    private Integer sortOrder = 0;

    /** active | deprecated | ignored — ignored/deprecated stay in the DB but leave the default UI. */
    @Column(nullable = false)
    private String status = "active";

    private Instant deletedAt;

    /** Stable tag applications send as X-Logos-Workflow-Tag to attribute traffic. */
    private String tag;

    public Integer getId() { return id; }
    public Integer getAnalysisId() { return analysisId; }
    public String getName() { return name; }
    public String getTriggerSummary() { return triggerSummary; }
    public String getDiagramMermaid() { return diagramMermaid; }
    public Integer getSortOrder() { return sortOrder; }
    public String getStatus() { return status; }
    public Instant getDeletedAt() { return deletedAt; }
    public String getTag() { return tag; }

    public void setAnalysisId(Integer analysisId) { this.analysisId = analysisId; }
    public void setName(String name) { this.name = name; }
    public void setTriggerSummary(String triggerSummary) { this.triggerSummary = triggerSummary; }
    public void setDiagramMermaid(String diagramMermaid) { this.diagramMermaid = diagramMermaid; }
    public void setSortOrder(Integer sortOrder) { this.sortOrder = sortOrder; }
    public void setStatus(String status) { this.status = status; }
    public void setDeletedAt(Instant deletedAt) { this.deletedAt = deletedAt; }
    public void setTag(String tag) { this.tag = tag; }
}
