package de.tum.cit.aet.logos.logoswebservice.notifications.repository;

import java.util.Collection;
import java.util.List;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.notifications.entity.Notification;
import de.tum.cit.aet.logos.logoswebservice.notifications.entity.RecipientKind;

/**
 * The inbox queries. A notification is visible to a user when any recipient
 * row matches their own id, one of their roles, or one of their teams. The
 * three {@code kind*} parameters pin the {@link RecipientKind} literal so the
 * query does not depend on enum-name resolution in JPQL.
 *
 * <p>The shared fragments are plain strings (not text blocks) and are spliced
 * with explicit spaces at the call sites: text blocks strip trailing
 * whitespace, which would glue {@code WHERE} to the following {@code EXISTS}.
 */
public interface NotificationRepository extends JpaRepository<Notification, Long> {

    /** A recipient row matches the user's id, one of their roles, or a team. */
    String RECIPIENT_MATCH = """
        EXISTS (
            SELECT 1 FROM NotificationRecipient r
            WHERE r.notificationId = n.id
              AND ( (r.recipientKind = :kindUser AND r.recipientId = :userId)
                 OR (r.recipientKind = :kindRole AND r.recipientRole = :role)
                 OR (r.recipientKind = :kindTeam AND r.recipientId IN :teamIds) )
        )
        """;

    /** Keep the row when not filtering, or when the user has not read it. */
    String UNREAD_FILTER = """
        (
            :unreadOnly = false
            OR NOT EXISTS (
                SELECT 1 FROM NotificationRead rd
                WHERE rd.notificationId = n.id AND rd.userId = :userId)
        )
        """;

    @Query("SELECT DISTINCT n FROM Notification n WHERE " + RECIPIENT_MATCH
        + " AND " + UNREAD_FILTER
        + " ORDER BY n.createdAt DESC, n.id DESC")
    Page<Notification> findForUser(
        @Param("userId") Integer userId,
        @Param("role") String role,
        @Param("teamIds") List<Integer> teamIds,
        @Param("unreadOnly") boolean unreadOnly,
        @Param("kindUser") RecipientKind kindUser,
        @Param("kindRole") RecipientKind kindRole,
        @Param("kindTeam") RecipientKind kindTeam,
        Pageable pageable);

    @Query("SELECT COUNT(DISTINCT n.id) FROM Notification n WHERE " + RECIPIENT_MATCH
        + " AND " + UNREAD_FILTER)
    long countForUser(
        @Param("userId") Integer userId,
        @Param("role") String role,
        @Param("teamIds") List<Integer> teamIds,
        @Param("unreadOnly") boolean unreadOnly,
        @Param("kindUser") RecipientKind kindUser,
        @Param("kindRole") RecipientKind kindRole,
        @Param("kindTeam") RecipientKind kindTeam);

    /** Whether the notification exists and is addressed to this user. */
    @Query("SELECT COUNT(n) > 0 FROM Notification n WHERE n.id = :notificationId AND " + RECIPIENT_MATCH)
    boolean existsForUser(
        @Param("notificationId") Long notificationId,
        @Param("userId") Integer userId,
        @Param("role") String role,
        @Param("teamIds") List<Integer> teamIds,
        @Param("kindUser") RecipientKind kindUser,
        @Param("kindRole") RecipientKind kindRole,
        @Param("kindTeam") RecipientKind kindTeam);

    /**
     * Of the given users, those who are active and addressed by the
     * notification right now: directly, through their current role, or
     * through a team they are currently a member of. Live delivery checks this
     * on every push, so revoked access stops the push as it stops the inbox.
     */
    @Query(value = """
        SELECT u.id FROM users u
        WHERE u.id IN (:userIds)
          AND u.is_active
          AND EXISTS (
              SELECT 1 FROM notification_recipients r
              WHERE r.notification_id = :notificationId
                AND ( (r.recipient_kind = 'user' AND r.recipient_id = u.id)
                   OR (r.recipient_kind = 'role' AND r.recipient_role = u.role)
                   OR (r.recipient_kind = 'team' AND r.recipient_id IN (
                          SELECT tm.team_id FROM team_members tm WHERE tm.user_id = u.id)) ))
        """, nativeQuery = true)
    List<Integer> findAddressedActiveUsers(
        @Param("notificationId") Long notificationId,
        @Param("userIds") Collection<Integer> userIds);
}
