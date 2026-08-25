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
    private boolean supportsFunctionCalling;

    @Column(nullable = false)
    private boolean supportsVision;

    @Column(nullable = false)
    private boolean supportsReasoning;

    @Column(name = "manual_override", nullable = false)
    private boolean manualOverride;

    public ModelCapabilities() {}

    public ModelCapabilities(Integer modelId, boolean supportsFunctionCalling, boolean supportsVision, boolean supportsReasoning) {
        this.modelId = modelId;
        this.supportsFunctionCalling = supportsFunctionCalling;
        this.supportsVision = supportsVision;
        this.supportsReasoning = supportsReasoning;
    }


    public Integer getId() { return id; }
    public Integer getModelId() { return modelId; }
    public boolean getSupportsFunctionCalling() { return supportsFunctionCalling; }
    public boolean getSupportsVision() { return supportsVision; }
    public boolean getSupportsReasoning() { return supportsReasoning; }
    public boolean getManualOverride() { return manualOverride; }

    public void setModelId(Integer modelId) { this.modelId = modelId; }
    public void setSupportsFunctionCalling(boolean supportsFunctionCalling) { this.supportsFunctionCalling = supportsFunctionCalling; }
    public void setSupportsVision(boolean supportsVision) { this.supportsVision = supportsVision; }
    public void setSupportsReasoning(boolean supportsReasoning) { this.supportsReasoning = supportsReasoning; }
    public void setManualOverride(boolean manualOverride) { this.manualOverride = manualOverride; }
}
