package de.tum.cit.aet.logos.logoswebservice.operations.repository;

public interface RuntimeByColdStartProjection {
    String getKind();
    Long getCount();
    Double getAvgRunSeconds();
}
