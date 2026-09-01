package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "model_aliases")
public class ModelAlias {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(name = "model_id", nullable = false)
    private Integer modelId;

    @Column(nullable = false)
    private String alias;

    public Integer getId() { return id; }
    public Integer getModelId() { return modelId; }
    public String getAlias() { return alias; }

    public void setModelId(Integer modelId) { this.modelId = modelId; }
    public void setAlias(String alias) { this.alias = alias; }
}
