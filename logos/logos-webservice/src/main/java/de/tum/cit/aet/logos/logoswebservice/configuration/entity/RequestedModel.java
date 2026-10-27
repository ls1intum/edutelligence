package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * A model that users have requested but that Logos does not serve yet.
 *
 * This is the registry: one row per requested model. Who voted for it lives in
 * {@link RequestedModelVote} (one row per voter), so the model's vote count is
 * the number of votes pointing at it. A model an admin adds to {@code models}
 * is no longer "requested" and is filtered out of the listing.
 */
@Entity
@Table(name = "requested_models")
public class RequestedModel {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(nullable = false)
    private String name;

    /**
     * The decisive Hugging Face gating verdict for this name: true when the
     * Hub rejects the repository with the model-gated reason, false when it
     * is reachable or rejected for another reason; null until the precheck
     * has produced a verdict — a timeout is no verdict and leaves this empty.
     */
    private Boolean isGated;

    /**
     * The team that first requested this model: set when the row is created
     * (or filled in on a row that predates the column) and never overwritten
     * — later votes from other teams count toward the total, they just do
     * not change who requested first. The team's app admin is the one who
     * accepts a gated model's license agreement.
     */
    private Integer firstRequestingTeam;

    public Integer getId() { return id; }
    public String getName() { return name; }
    public Boolean getIsGated() { return isGated; }
    public Integer getFirstRequestingTeam() { return firstRequestingTeam; }

    public void setName(String name) { this.name = name; }
    public void setIsGated(Boolean isGated) { this.isGated = isGated; }
    public void setFirstRequestingTeam(Integer firstRequestingTeam) { this.firstRequestingTeam = firstRequestingTeam; }
}
