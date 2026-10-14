package de.tum.cit.aet.logos.logoswebservice.notifications.realtime;

import java.util.List;
import java.util.Set;

import org.springframework.web.socket.WebSocketSession;

import de.tum.cit.aet.logos.logoswebservice.notifications.dto.NotificationTargetDTO;
import de.tum.cit.aet.logos.logoswebservice.notifications.entity.RecipientKind;

/**
 * One open notification socket and the identity it was opened with.
 *
 * <p>Role and team ids are captured at the handshake. A membership change
 * reaches the socket on its next reconnect; the inbox and the unread count
 * read the database, so they are never affected by this snapshot.
 */
record ConnectedInbox(WebSocketSession session, Integer userId, String role, Set<Integer> teamIds) {

    /** Same rule as the inbox query: any target matching the user, role, or a team. */
    boolean isAddressedBy(List<NotificationTargetDTO> targets) {
        for (NotificationTargetDTO target : targets) {
            RecipientKind kind = RecipientKind.fromValue(target.kind()).orElse(null);
            if (kind == RecipientKind.user && userId.equals(target.id())
                || kind == RecipientKind.role && role != null && role.equals(target.role())
                || kind == RecipientKind.team && target.id() != null && teamIds.contains(target.id())) {
                return true;
            }
        }
        return false;
    }
}
