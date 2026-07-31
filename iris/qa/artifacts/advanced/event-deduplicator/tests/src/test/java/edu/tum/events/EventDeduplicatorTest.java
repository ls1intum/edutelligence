package edu.tum.events;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import org.junit.jupiter.api.Test;

class EventDeduplicatorTest {
    @Test
    void scopesIdentifiersByPartition() {
        var deduplicator = new EventDeduplicator(60);
        assertTrue(deduplicator.accept(new Event("orders", "42", 1_000L)));
        assertTrue(deduplicator.accept(new Event("payments", "42", 2_000L)));
    }

    @Test
    void acceptsTheSameEventAfterTheWindow() {
        var deduplicator = new EventDeduplicator(60);
        assertTrue(deduplicator.accept(new Event("orders", "42", 1_000L)));
        assertFalse(deduplicator.accept(new Event("orders", "42", 60_999L)));
        assertTrue(deduplicator.accept(new Event("orders", "42", 62_000L)));
    }
}
