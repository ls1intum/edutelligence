package de.tum.cit.aet.logos.logoswebservice.identity;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.util.List;

import org.junit.jupiter.api.Test;

class ObjectivePriorityTest {

    @Test
    void forSloUsesLatencyFirstForUxCritical() {
        assertEquals(List.of("latency", "quality", "price"), ObjectivePriority.forSlo("ux-critical"));
    }

    @Test
    void forSloUsesPriceFirstForBackground() {
        assertEquals(List.of("price", "quality", "latency"), ObjectivePriority.forSlo("ux-background"));
    }

    @Test
    void normalizeFillsMissingKeysPreservingOrder() {
        assertEquals(
            List.of("price", "latency", "quality"),
            ObjectivePriority.normalize(List.of("price", "latency", "unknown")));
    }

    @Test
    void normalizeEmptyFallsBackToDefault() {
        assertEquals(ObjectivePriority.DEFAULT, ObjectivePriority.normalize(List.of()));
    }
}
