package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "model_capabilities")
public class ModelCapabilities {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(name = "model_id", nullable = false, unique = true)
    private Integer modelId;

    @Column(nullable = false)
    private Boolean supportsFunctionCalling;

    @Column(nullable = false)
    private Boolean supportsVision;

    @Column(nullable = false)
    private Boolean supportsReasoning;

    public ModelCapabilities() {}

    public ModelCapabilities(Integer modelId, Boolean supportsFunctionCalling, Boolean supportsVision, Boolean supportsReasoning) {
        this.modelId = modelId;
        this.supportsFunctionCalling = supportsFunctionCalling;
        this.supportsVision = supportsVision;
        this.supportsReasoning = supportsReasoning;
    }


    public Integer getId() { return id; }
    public Integer getModelId() { return modelId; }
    public Boolean getSupportsFunctionCalling() { return supportsFunctionCalling; }
    public Boolean getSupportsVision() { return supportsVision; }
    public Boolean getSupportsReasoning() { return supportsReasoning; }

    public void setModelId(Integer modelId) { this.modelId = modelId; }
    public void setSupportsFunctionCalling(Boolean supportsFunctionCalling) { this.supportsFunctionCalling = supportsFunctionCalling; }
    public void setSupportsVision(Boolean supportsVision) { this.supportsVision = supportsVision; }
    public void setSupportsReasoning(Boolean supportsReasoning) { this.supportsReasoning = supportsReasoning; }
}
