package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * One user's vote for a requested model.
 *
 * The {@code (requested_model_id, user_id)} pair is unique (see migration 034),
 * which is what enforces "one vote per voter per model". Deleting a row takes
 * the vote back; re-inserting it casts it again.
 */
@Entity
@Table(name = "requested_model_votes")
public class RequestedModelVote {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(name = "requested_model_id", nullable = false)
    private Integer requestedModelId;

    @Column(name = "user_id", nullable = false)
    private Integer userId;

    public Integer getId() { return id; }
    public Integer getRequestedModelId() { return requestedModelId; }
    public Integer getUserId() { return userId; }

    public void setRequestedModelId(Integer requestedModelId) { this.requestedModelId = requestedModelId; }
    public void setUserId(Integer userId) { this.userId = userId; }
}
