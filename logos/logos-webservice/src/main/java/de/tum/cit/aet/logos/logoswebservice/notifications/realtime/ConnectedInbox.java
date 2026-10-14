package de.tum.cit.aet.logos.logoswebservice.notifications.realtime;

import org.springframework.web.socket.WebSocketSession;

/**
 * One open notification socket and the user it was opened by. What that user
 * may receive is not captured here: it is checked against the database on
 * every push, so a removed membership, a changed role, or a deactivated
 * account takes effect on the next notification.
 */
record ConnectedInbox(WebSocketSession session, Integer userId) {
}
