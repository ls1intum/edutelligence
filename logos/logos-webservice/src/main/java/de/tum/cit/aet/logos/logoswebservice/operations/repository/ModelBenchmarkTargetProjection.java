package de.tum.cit.aet.logos.logoswebservice.operations.repository;

public interface ModelBenchmarkTargetProjection {
    Integer getModelProviderId();
    Integer getProviderId();
    String getProviderName();
    String getProviderType();
    Integer getModelId();
    String getModelName();
    Boolean getEndpointConfigured();
    Boolean getAuthenticationConfigured();
}
