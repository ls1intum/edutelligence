package de.tum.cit.aet.logos.logoswebservice.notifications.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * A per-user "seen" marker. Unread-ness is the absence of a row here for the
 * viewer, so it is computed rather than stored on the notification.
 */
@Entity
@Table(name = "notification_reads")
public class NotificationRead {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long notificationId;

    @Column(nullable = false)
    private Integer userId;

    @Column(nullable = false)
    private Instant readAt;

    public Long getId() { return id; }
    public Long getNotificationId() { return notificationId; }
    public Integer getUserId() { return userId; }
    public Instant getReadAt() { return readAt; }

    public void setId(Long id) { this.id = id; }
    public void setNotificationId(Long notificationId) { this.notificationId = notificationId; }
    public void setUserId(Integer userId) { this.userId = userId; }
    public void setReadAt(Instant readAt) { this.readAt = readAt; }
}
