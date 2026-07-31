package edu.tum.events;

public final class EventDeduplicator {
    private final long windowMillis;
    private final SeenEventStore store = new SeenEventStore();

    public EventDeduplicator(long windowSeconds) {
        this.windowMillis = Math.multiplyExact(windowSeconds, 1_000L);
    }

    public boolean accept(Event event) {
        return store.recordIfOutsideWindow(event, windowMillis);
    }
}
