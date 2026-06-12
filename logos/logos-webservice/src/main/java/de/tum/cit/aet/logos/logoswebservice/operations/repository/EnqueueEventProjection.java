package de.tum.cit.aet.logos.logoswebservice.operations.repository;

import java.time.Instant;

public interface EnqueueEventProjection {
    String getRequestId();
    Instant getEnqueueTs();
    String getPrivacyLevel();
}
