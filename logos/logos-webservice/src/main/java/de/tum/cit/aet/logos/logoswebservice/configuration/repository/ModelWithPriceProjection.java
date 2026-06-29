package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.math.BigDecimal;

public interface ModelWithPriceProjection {
    Integer getId();
    String getName();
    Integer getWeightLatency();
    Integer getWeightAccuracy();
    Integer getWeightCost();
    Integer getWeightQuality();
    String getTags();
    Integer getParallel();
    String getDescription();
    BigDecimal getInputUsdPerMillion();
    BigDecimal getOutputUsdPerMillion();
}
