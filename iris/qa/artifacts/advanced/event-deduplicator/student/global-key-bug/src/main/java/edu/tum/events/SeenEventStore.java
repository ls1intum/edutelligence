package edu.tum.events;

import java.util.HashMap;
import java.util.Map;

final class SeenEventStore {
    private final Map<String, Long> lastSeenMillis = new HashMap<>();

    boolean recordIfOutsideWindow(Event event, long windowMillis) {
        var previous = lastSeenMillis.get(event.eventId());
        if (previous != null && event.timestampMillis() - previous < windowMillis) {
            return false;
        }
        lastSeenMillis.put(event.eventId(), event.timestampMillis());
        return true;
    }
}
