package de.tum.cit.aet.logos.logoswebservice.identity.entity;

import java.util.List;

import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "ai_workflow_steps")
public class AiWorkflowStep {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(nullable = false)
    private Integer workflowId;

    @Column(nullable = false)
    private String name;

    @Column(nullable = false)
    private Integer sortOrder = 0;

    private String tag;

    @Column(nullable = false)
    private String recommendedSlo;

    private String confirmedSlo;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "objective_priority", columnDefinition = "jsonb", nullable = false)
    private List<Object> objectivePriority = List.of("latency", "quality", "price");

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "confirmed_objective_priority", columnDefinition = "jsonb")
    private List<Object> confirmedObjectivePriority;

    public Integer getId() { return id; }
    public Integer getWorkflowId() { return workflowId; }
    public String getName() { return name; }
    public Integer getSortOrder() { return sortOrder; }
    public String getTag() { return tag; }
    public String getRecommendedSlo() { return recommendedSlo; }
    public String getConfirmedSlo() { return confirmedSlo; }
    public List<Object> getObjectivePriority() { return objectivePriority; }
    public List<Object> getConfirmedObjectivePriority() { return confirmedObjectivePriority; }

    public void setWorkflowId(Integer workflowId) { this.workflowId = workflowId; }
    public void setName(String name) { this.name = name; }
    public void setSortOrder(Integer sortOrder) { this.sortOrder = sortOrder; }
    public void setTag(String tag) { this.tag = tag; }
    public void setRecommendedSlo(String recommendedSlo) { this.recommendedSlo = recommendedSlo; }
    public void setConfirmedSlo(String confirmedSlo) { this.confirmedSlo = confirmedSlo; }
    public void setObjectivePriority(List<Object> objectivePriority) {
        this.objectivePriority = objectivePriority;
    }
    public void setConfirmedObjectivePriority(List<Object> confirmedObjectivePriority) {
        this.confirmedObjectivePriority = confirmedObjectivePriority;
    }
}
