package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import org.junit.jupiter.api.Test;

import com.fasterxml.jackson.databind.ObjectMapper;

import static org.assertj.core.api.Assertions.assertThat;

class ModelServiceUnitTest {

    private final ModelService svc = new ModelService(null, null, null, null, null, null, null, null, new ObjectMapper());

    @Test
    void parseWeightOverrides_jsonNullLiteral_returnsEmptyMap() {
        // A jsonb NOT NULL column stores the JSON literal "null" as a valid
        // value; readValue turns it into Java null without throwing, and the
        // response field must still render as a map.
        assertThat(svc.parseWeightOverrides("null")).isEmpty();
    }

    @Test
    void parseWeightOverrides_stillParsesRealOverrideMaps() {
        // The null normalization must not swallow real pin sets.
        assertThat(svc.parseWeightOverrides("{\"latency\": true, \"cost\": false}"))
            .containsEntry("latency", true)
            .containsEntry("cost", false);
    }
}
