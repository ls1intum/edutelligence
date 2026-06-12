package de.tum.cit.aet.logos.logoswebservice.operations.repository;

public interface TimeSeriesProjection {
    Double getBucketTs();
    Long getTotal();
    Long getCloud();
    Long getLocal();
    Double getAvgRunSeconds();
    Double getAvgVram();
}
