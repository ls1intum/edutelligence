package de.tum.cit.aet.logos.logoswebservice.notifications.repository;

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

    /** Every notification id addressed to this user (read or unread). */
    @Query("SELECT n.id FROM Notification n WHERE " + RECIPIENT_MATCH)
    List<Long> findIdsForUser(
        @Param("userId") Integer userId,
        @Param("role") String role,
        @Param("teamIds") List<Integer> teamIds,
        @Param("kindUser") RecipientKind kindUser,
        @Param("kindRole") RecipientKind kindRole,
        @Param("kindTeam") RecipientKind kindTeam);
}
