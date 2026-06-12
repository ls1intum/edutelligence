package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

public interface PolicyProjection {
    Integer getId();
    Integer getApiKeyId();
    Integer getTeamId();
    String getName();
    String getDescription();
    String getThresholdPrivacy();
    Integer getThresholdLatency();
    Integer getThresholdAccuracy();
    Integer getThresholdCost();
    Integer getThresholdQuality();
    Integer getPriority();
    String getTopic();
}
