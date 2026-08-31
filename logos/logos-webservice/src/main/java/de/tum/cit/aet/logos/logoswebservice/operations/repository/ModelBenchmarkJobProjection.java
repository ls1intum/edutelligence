package de.tum.cit.aet.logos.logoswebservice.operations.repository;

import java.time.Instant;

public interface ModelBenchmarkJobProjection {
    Integer getId();
    String getStatus();
    String getRequestPayloadJson();
    String getResultPayloadJson();
    String getErrorMessage();
    Instant getCreatedAt();
    Instant getUpdatedAt();
}
