package de.tum.cit.aet.logos.logoswebservice.operations.repository;

public interface ModelTimeSeriesProjection {
    Double getBucketTs();
    Integer getModelId();
    String getModelName();
    Long getCount();
}
