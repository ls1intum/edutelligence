package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

import java.util.HashMap;
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
    private String description;

    /**
     * Classifications-weight dimensions (latency/accuracy/cost/quality) the
     * admin set manually. The metrics derivation never overwrites a dimension
     * that carries an override.
     */
    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "weight_overrides", columnDefinition = "jsonb", nullable = false)
    private Map<String, Boolean> weightOverrides = new HashMap<>();

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "profile_ratings", columnDefinition = "jsonb", nullable = false)
    private Map<String, Integer> profileRatings = Map.of();

    public Integer getId() { return id; }
    public String getName() { return name; }
    public Integer getWeightLatency() { return weightLatency; }
    public Integer getWeightAccuracy() { return weightAccuracy; }
    public Integer getWeightCost() { return weightCost; }
    public Integer getWeightQuality() { return weightQuality; }
    public String getTags() { return tags; }
    public String getDescription() { return description; }
    public Map<String, Boolean> getWeightOverrides() { return weightOverrides; }
    public Map<String, Integer> getProfileRatings() { return profileRatings; }

    public void setName(String name) { this.name = name; }
    public void setWeightLatency(Integer w) { this.weightLatency = w; }
    public void setWeightAccuracy(Integer w) { this.weightAccuracy = w; }
    public void setWeightCost(Integer w) { this.weightCost = w; }
    public void setWeightQuality(Integer w) { this.weightQuality = w; }
    public void setTags(String tags) { this.tags = tags; }
    public void setDescription(String description) { this.description = description; }
    public void setWeightOverrides(Map<String, Boolean> weightOverrides) { this.weightOverrides = weightOverrides; }
    public void setProfileRatings(Map<String, Integer> profileRatings) {
        this.profileRatings = profileRatings != null ? profileRatings : Map.of();
    }
}
