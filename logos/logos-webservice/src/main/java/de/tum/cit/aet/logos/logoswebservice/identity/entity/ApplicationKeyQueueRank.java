package de.tum.cit.aet.logos.logoswebservice.identity.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "application_key_queue_ranks")
public class ApplicationKeyQueueRank {

    @Id
    private Integer apiKeyId;

    @Column(nullable = false)
    private Integer rank;

    @Column(nullable = false)
    private Instant updatedAt = Instant.now();

    private Integer updatedBy;

    public Integer getApiKeyId() { return apiKeyId; }
    public Integer getRank() { return rank; }
    public Instant getUpdatedAt() { return updatedAt; }
    public Integer getUpdatedBy() { return updatedBy; }

    public void setApiKeyId(Integer apiKeyId) { this.apiKeyId = apiKeyId; }
    public void setRank(Integer rank) { this.rank = rank; }
    public void setUpdatedAt(Instant updatedAt) { this.updatedAt = updatedAt; }
    public void setUpdatedBy(Integer updatedBy) { this.updatedBy = updatedBy; }
}
