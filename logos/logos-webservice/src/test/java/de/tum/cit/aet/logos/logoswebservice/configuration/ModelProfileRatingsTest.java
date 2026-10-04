package de.tum.cit.aet.logos.logoswebservice.configuration;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.Map;

import org.junit.jupiter.api.Test;

class ModelProfileRatingsTest {

    @Test
    void normalizeKeepsLikertScoresAndDropsOutOfRange() {
        Map<String, Integer> out = ModelProfileRatings.normalize(
            Map.of("Latency", 5, "quality", 0, "price", 3, "extra", 4));
        assertEquals(5, out.get("latency"));
        assertEquals(3, out.get("price"));
        assertEquals(4, out.get("extra"));
        assertTrue(!out.containsKey("quality"));
    }
}
