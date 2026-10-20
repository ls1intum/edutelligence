package de.tum.cit.aet.logos.logoswebservice.notifications.entity;

import java.time.Instant;

import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * One stored event: what happened, who triggered it, and when. The event
 * specific details live in {@link #payload}; the audience is on
 * {@code notification_recipients}, and per-user read state on
 * {@code notification_reads}.
 */
@Entity
@Table(name = "notifications")
public class Notification {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private NotificationType type;

    @Column(nullable = false)
    private String title;

    private String body;

    /** Event-specific structured data, stored as JSONB and surfaced as-is. */
    @JdbcTypeCode(SqlTypes.JSON)
    @Column(columnDefinition = "jsonb")
    private String payload;

    /** Which service emitted it: {@code webservice} or {@code orchestrator}. */
    @Column(nullable = false)
    private String source;

    private Integer actorUserId;

    @Column(nullable = false)
    private Instant createdAt;

    public Long getId() { return id; }
    public NotificationType getType() { return type; }
    public String getTitle() { return title; }
    public String getBody() { return body; }
    public String getPayload() { return payload; }
    public String getSource() { return source; }
    public Integer getActorUserId() { return actorUserId; }
    public Instant getCreatedAt() { return createdAt; }

    public void setId(Long id) { this.id = id; }
    public void setType(NotificationType type) { this.type = type; }
    public void setTitle(String title) { this.title = title; }
    public void setBody(String body) { this.body = body; }
    public void setPayload(String payload) { this.payload = payload; }
    public void setSource(String source) { this.source = source; }
    public void setActorUserId(Integer actorUserId) { this.actorUserId = actorUserId; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }
}
