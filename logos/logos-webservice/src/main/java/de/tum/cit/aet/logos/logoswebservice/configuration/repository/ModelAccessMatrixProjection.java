package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

/**
 * One row of the model access matrix: a team's model grant plus its grant
 * state for one hosting provider. A model without any hosting provider
 * yields exactly one row per team with both provider fields null.
 */
public interface ModelAccessMatrixProjection {
    Integer getTeamId();
    String getTeamName();
    Boolean getModelGrant();
    Integer getProviderId();
    Boolean getProviderGrant();
}
