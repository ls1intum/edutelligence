package de.tum.cit.aet.logos.logoswebservice.operations.repository;

/**
 * One entry of the statistics page's team / requester filter: an id, something
 * to show for it, and how many requests picking it would select.
 *
 * The count is part of the option rather than a detail behind it — a dropdown
 * of names says nothing about which of them are worth opening, and the ordering
 * (busiest first) only makes sense to the reader once the numbers are visible.
 */
public interface ScopeOptionProjection {
    Integer getId();
    String getLabel();
    long getRequestCount();
}
