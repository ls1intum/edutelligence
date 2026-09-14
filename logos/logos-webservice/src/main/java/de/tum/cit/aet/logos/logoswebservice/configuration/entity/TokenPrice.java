package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "token_prices")
public class TokenPrice {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(nullable = false)
    private Integer typeId;

    private Integer modelId;
    private Integer providerId;

    /** Pricing unit for this row: token | character | request | image | page | pixel | millisecond | query. */
    @Column(nullable = false)
    private String unit = "token";

    /** Row applies when the response's prompt size is at least this many tokens (context-length tiers). */
    @Column(name = "min_context_tokens", nullable = false)
    private Long minContextTokens = 0L;

    /** Row applies for this service tier ('default', 'flex', 'priority', 'scale', ...). */
    @Column(name = "service_tier", nullable = false)
    private String serviceTier = "default";

    @Column(nullable = false)
    private Instant validFrom;

    /** Micro-cents per 1000 units of {@link #unit}. */
    @Column(name = "price_per_k_unit", nullable = false)
    private Long pricePerKUnit;

    public TokenPrice() {}

    public Integer getId() { return id; }
    public Integer getTypeId() { return typeId; }
    public Integer getModelId() { return modelId; }
    public Integer getProviderId() { return providerId; }
    public String getUnit() { return unit; }
    public Long getMinContextTokens() { return minContextTokens; }
    public String getServiceTier() { return serviceTier; }
    public Instant getValidFrom() { return validFrom; }
    public Long getPricePerKUnit() { return pricePerKUnit; }

    public void setTypeId(Integer typeId) { this.typeId = typeId; }
    public void setModelId(Integer modelId) { this.modelId = modelId; }
    public void setProviderId(Integer providerId) { this.providerId = providerId; }
    public void setUnit(String unit) { this.unit = unit; }
    public void setMinContextTokens(Long minContextTokens) { this.minContextTokens = minContextTokens; }
    public void setServiceTier(String serviceTier) { this.serviceTier = serviceTier; }
    public void setValidFrom(Instant validFrom) { this.validFrom = validFrom; }
    public void setPricePerKUnit(Long pricePerKUnit) { this.pricePerKUnit = pricePerKUnit; }
}
