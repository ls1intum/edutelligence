package de.tum.cit.aet.logos.logoswebservice.notifications.repository;

import java.util.Collection;
import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.notifications.entity.NotificationRead;

public interface NotificationReadRepository extends JpaRepository<NotificationRead, Long> {

    /** Read markers of one user, limited to the given notifications (one inbox page). */
    List<NotificationRead> findByUserIdAndNotificationIdIn(Integer userId, Collection<Long> notificationIds);

    /**
     * Record a read marker unless one exists. Conflict-tolerant so concurrent
     * single-item and mark-all requests never fail on {@code uq_notification_reads}.
     *
     * @return 1 if a marker was inserted, 0 if it already existed
     */
    @Modifying
    @Query(value = """
        INSERT INTO notification_reads (notification_id, user_id, read_at)
        VALUES (:notificationId, :userId, now())
        ON CONFLICT (notification_id, user_id) DO NOTHING
        """, nativeQuery = true)
    int insertIfAbsent(@Param("notificationId") Long notificationId, @Param("userId") Integer userId);

    /**
     * Mark every notification addressed to the user read in one statement:
     * directly, through the role, or through a team the user is a member of.
     * Only unread rows are inserted; ON CONFLICT covers a concurrent read.
     *
     * @return the number of read markers added
     */
    @Modifying
    @Query(value = """
        INSERT INTO notification_reads (notification_id, user_id, read_at)
        SELECT n.id, :userId, now()
        FROM notifications n
        WHERE NOT EXISTS (
                SELECT 1 FROM notification_reads rd
                WHERE rd.notification_id = n.id AND rd.user_id = :userId)
          AND EXISTS (
                SELECT 1 FROM notification_recipients r
                WHERE r.notification_id = n.id
                  AND ( (r.recipient_kind = 'user' AND r.recipient_id = :userId)
                     OR (r.recipient_kind = 'role' AND r.recipient_role = :role)
                     OR (r.recipient_kind = 'team' AND r.recipient_id IN (
                            SELECT tm.team_id FROM team_members tm WHERE tm.user_id = :userId)) ))
        ON CONFLICT (notification_id, user_id) DO NOTHING
        """, nativeQuery = true)
    int insertAllAddressed(@Param("userId") Integer userId, @Param("role") String role);
}
