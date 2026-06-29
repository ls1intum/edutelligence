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

    @Column(nullable = false)
    private Instant validFrom;

    @Column(name = "price_per_k_token", nullable = false)
    private Long pricePerKToken;

    public TokenPrice() {}

    public Integer getId() { return id; }
    public Integer getTypeId() { return typeId; }
    public Integer getModelId() { return modelId; }
    public Integer getProviderId() { return providerId; }
    public Instant getValidFrom() { return validFrom; }
    public Long getPricePerKToken() { return pricePerKToken; }

    public void setTypeId(Integer typeId) { this.typeId = typeId; }
    public void setModelId(Integer modelId) { this.modelId = modelId; }
    public void setProviderId(Integer providerId) { this.providerId = providerId; }
    public void setValidFrom(Instant validFrom) { this.validFrom = validFrom; }
    public void setPricePerKToken(Long pricePerKToken) { this.pricePerKToken = pricePerKToken; }
}
