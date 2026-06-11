package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

public record UpdatePolicyRequestDTO(
    Integer id,
    String name,
    String description,
    String thresholdPrivacy,
    Integer thresholdLatency,
    Integer thresholdAccuracy,
    Integer thresholdCost,
    Integer thresholdQuality,
    Integer priority,
    String topic,
    Integer apiKeyId,
    Integer teamId
) {}
