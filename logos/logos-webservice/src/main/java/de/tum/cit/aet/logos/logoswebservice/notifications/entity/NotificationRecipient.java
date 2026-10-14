package de.tum.cit.aet.logos.logoswebservice.notifications.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * One fan-out target of a notification: the user, team or role it is
 * addressed to. A notification typically has several of these, which is what
 * lets a single event reach a whole role or team without one row per person.
 */
@Entity
@Table(name = "notification_recipients")
public class NotificationRecipient {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long notificationId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private RecipientKind recipientKind;

    /** User id ({@link RecipientKind#USER}) or team id ({@link RecipientKind#TEAM}); null for a role. */
    private Integer recipientId;

    /** Role value ({@link RecipientKind#ROLE}); null for user/team. */
    private String recipientRole;

    public Long getId() { return id; }
    public Long getNotificationId() { return notificationId; }
    public RecipientKind getRecipientKind() { return recipientKind; }
    public Integer getRecipientId() { return recipientId; }
    public String getRecipientRole() { return recipientRole; }

    public void setId(Long id) { this.id = id; }
    public void setNotificationId(Long notificationId) { this.notificationId = notificationId; }
    public void setRecipientKind(RecipientKind recipientKind) { this.recipientKind = recipientKind; }
    public void setRecipientId(Integer recipientId) { this.recipientId = recipientId; }
    public void setRecipientRole(String recipientRole) { this.recipientRole = recipientRole; }
}
