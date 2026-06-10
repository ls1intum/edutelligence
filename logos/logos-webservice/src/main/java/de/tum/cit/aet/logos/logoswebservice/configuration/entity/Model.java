package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "models")
public class Model {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(nullable = false)
    private String name;

    private Integer weightLatency = 0;
    private Integer weightAccuracy = 0;
    private Integer weightCost = 0;
    private Integer weightQuality = 0;
    private String tags;
    private Integer parallel = 1;
    private String description;

    public Integer getId() { return id; }
    public String getName() { return name; }
    public Integer getWeightLatency() { return weightLatency; }
    public Integer getWeightAccuracy() { return weightAccuracy; }
    public Integer getWeightCost() { return weightCost; }
    public Integer getWeightQuality() { return weightQuality; }
    public String getTags() { return tags; }
    public Integer getParallel() { return parallel; }
    public String getDescription() { return description; }

    public void setName(String name) { this.name = name; }
    public void setWeightLatency(Integer w) { this.weightLatency = w; }
    public void setWeightAccuracy(Integer w) { this.weightAccuracy = w; }
    public void setWeightCost(Integer w) { this.weightCost = w; }
    public void setWeightQuality(Integer w) { this.weightQuality = w; }
    public void setTags(String tags) { this.tags = tags; }
    public void setParallel(Integer parallel) { this.parallel = parallel; }
    public void setDescription(String description) { this.description = description; }
}
