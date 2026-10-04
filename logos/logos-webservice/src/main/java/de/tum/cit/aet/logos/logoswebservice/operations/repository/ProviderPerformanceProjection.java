package de.tum.cit.aet.logos.logoswebservice.operations.repository;

public interface ProviderPerformanceProjection {
    Integer getProviderId();
    String getProviderName();
    Integer getModelId();
    String getModelName();
    Long getRequestCount();
    Long getSuccessfulRequestCount();
    Long getColdStartCount();
    Double getSuccessRate();
    Double getColdStartRate();
    Double getTtftP50Ms();
    Double getTtftP95Ms();
    Double getTtftP100Ms();
    Double getTpotP50Ms();
    Double getTpotP95Ms();
    Double getTpotP100Ms();
    Double getTtltP50Ms();
    Double getTtltP95Ms();
    Double getTtltP100Ms();
}
