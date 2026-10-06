package de.tum.cit.aet.logos.logoswebservice.identity.entity;

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

    /** The owner saved {@link #diagramMermaid}; the next analysis keeps it. */
    @Column(nullable = false)
    private boolean diagramSetByOwner;

    /** Agent Mermaid from a later analysis that differs from the owner's diagram. */
    private String proposedDiagramMermaid;

    public Integer getId() { return id; }
    public Integer getAnalysisId() { return analysisId; }
    public String getName() { return name; }
    public String getTriggerSummary() { return triggerSummary; }
    public String getDiagramMermaid() { return diagramMermaid; }
    public Integer getSortOrder() { return sortOrder; }
    public boolean isDiagramSetByOwner() { return diagramSetByOwner; }
    public String getProposedDiagramMermaid() { return proposedDiagramMermaid; }

    public void setAnalysisId(Integer analysisId) { this.analysisId = analysisId; }
    public void setName(String name) { this.name = name; }
    public void setTriggerSummary(String triggerSummary) { this.triggerSummary = triggerSummary; }
    public void setDiagramMermaid(String diagramMermaid) { this.diagramMermaid = diagramMermaid; }
    public void setSortOrder(Integer sortOrder) { this.sortOrder = sortOrder; }
    public void setDiagramSetByOwner(boolean diagramSetByOwner) { this.diagramSetByOwner = diagramSetByOwner; }
    public void setProposedDiagramMermaid(String proposedDiagramMermaid) {
        this.proposedDiagramMermaid = proposedDiagramMermaid;
    }
}
