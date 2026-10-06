package de.tum.cit.aet.logos.logoswebservice.identity.dto;

import java.util.List;

/**
 * Replace the Logos-admin ordered ranking of application keys.
 * Rank 1 is highest dequeue priority within equal SLA buckets.
 * Keys omitted from the list become unranked.
 */
public record ReplaceApplicationKeyQueueRanksRequestDTO(
    List<Integer> apiKeyIds
) {}
