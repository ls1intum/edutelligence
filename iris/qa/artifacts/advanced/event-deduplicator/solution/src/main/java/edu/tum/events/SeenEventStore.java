package edu.tum.events;

import java.util.HashMap;
import java.util.Map;

final class SeenEventStore {
    private final Map<EventKey, Long> lastSeenMillis = new HashMap<>();

    boolean recordIfOutsideWindow(Event event, long windowMillis) {
        var key = new EventKey(event.partition(), event.eventId());
        var previous = lastSeenMillis.get(key);
        if (previous != null && event.timestampMillis() - previous < windowMillis) {
            return false;
        }
        lastSeenMillis.put(key, event.timestampMillis());
        return true;
    }
}
