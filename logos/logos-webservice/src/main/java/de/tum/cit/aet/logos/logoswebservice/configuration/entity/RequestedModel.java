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

    public Integer getId() { return id; }
    public String getName() { return name; }

    public void setName(String name) { this.name = name; }
}
