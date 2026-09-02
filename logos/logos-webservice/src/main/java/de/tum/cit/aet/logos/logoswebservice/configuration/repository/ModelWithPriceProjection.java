package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.math.BigDecimal;
import java.time.Instant;

public interface ModelWithPriceProjection {
    Integer getId();
    String getName();
    Integer getWeightLatency();
    Integer getWeightAccuracy();
    Integer getWeightCost();
    Integer getWeightQuality();
    String getTags();
    String getAliases();
    String getDescription();
    BigDecimal getInputUsdPerMillion();
    BigDecimal getOutputUsdPerMillion();
    Instant getLastUsedAt();
    String getWeightOverridesText();
}
