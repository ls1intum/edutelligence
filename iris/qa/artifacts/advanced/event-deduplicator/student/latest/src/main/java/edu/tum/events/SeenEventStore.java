package edu.tum.events;

import java.util.HashMap;
import java.util.Map;

final class SeenEventStore {
    private final Map<String, Long> lastSeenMillis = new HashMap<>();

    boolean recordIfOutsideWindow(Event event, long windowMillis) {
        var previous = lastSeenMillis.get(event.eventId());
        var elapsedSeconds = previous == null ? Long.MAX_VALUE
            : (event.timestampMillis() - previous) / 1_000L;
        if (elapsedSeconds < windowMillis) {
            return false;
        }
        lastSeenMillis.put(event.eventId(), event.timestampMillis());
        return true;
    }
}
