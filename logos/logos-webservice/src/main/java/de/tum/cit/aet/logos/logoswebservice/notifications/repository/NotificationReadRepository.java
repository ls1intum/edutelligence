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
}
