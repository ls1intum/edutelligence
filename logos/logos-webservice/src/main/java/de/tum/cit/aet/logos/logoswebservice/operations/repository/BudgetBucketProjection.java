package de.tum.cit.aet.logos.logoswebservice.operations.repository;

import java.time.Instant;

public interface BudgetBucketProjection {
    Integer getTeamId();
    String getTeamName();
    Integer getApiKeyId();
    String getApiKeyName();
    Instant getBucketTs();
    Long getCostMicroCents();
}
