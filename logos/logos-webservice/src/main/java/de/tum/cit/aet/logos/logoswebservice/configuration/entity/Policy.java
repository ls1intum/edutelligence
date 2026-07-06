package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "policies")
public class Policy {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(nullable = false)
    private String name;

    private String description;

    @Enumerated(EnumType.STRING)
    @JdbcTypeCode(SqlTypes.NAMED_ENUM)
    @Column(columnDefinition = "threshold_enum", nullable = false)
    private ThresholdLevel thresholdPrivacy;

    @Column(nullable = false)
    private Integer thresholdLatency = 0;

    @Column(nullable = false)
    private Integer thresholdAccuracy = 0;

    @Column(nullable = false)
    private Integer thresholdCost = 0;

    @Column(nullable = false)
    private Integer thresholdQuality = 0;

    @Column(nullable = false)
    private Integer priority = 1;

    private String topic;
    private Integer apiKeyId;
    private Integer teamId;

    public Integer getId() { return id; }
    public String getName() { return name; }
    public String getDescription() { return description; }
    public ThresholdLevel getThresholdPrivacy() { return thresholdPrivacy; }
    public Integer getThresholdLatency() { return thresholdLatency; }
    public Integer getThresholdAccuracy() { return thresholdAccuracy; }
    public Integer getThresholdCost() { return thresholdCost; }
    public Integer getThresholdQuality() { return thresholdQuality; }
    public Integer getPriority() { return priority; }
    public String getTopic() { return topic; }
    public Integer getApiKeyId() { return apiKeyId; }
    public Integer getTeamId() { return teamId; }

    public void setName(String name) { this.name = name; }
    public void setDescription(String description) { this.description = description; }
    public void setThresholdPrivacy(ThresholdLevel thresholdPrivacy) { this.thresholdPrivacy = thresholdPrivacy; }
    public void setThresholdLatency(Integer thresholdLatency) { this.thresholdLatency = thresholdLatency; }
    public void setThresholdAccuracy(Integer thresholdAccuracy) { this.thresholdAccuracy = thresholdAccuracy; }
    public void setThresholdCost(Integer thresholdCost) { this.thresholdCost = thresholdCost; }
    public void setThresholdQuality(Integer thresholdQuality) { this.thresholdQuality = thresholdQuality; }
    public void setPriority(Integer priority) { this.priority = priority; }
    public void setTopic(String topic) { this.topic = topic; }
    public void setApiKeyId(Integer apiKeyId) { this.apiKeyId = apiKeyId; }
    public void setTeamId(Integer teamId) { this.teamId = teamId; }
}
