package de.tum.cit.aet.logos.logoswebservice.identity.dto;

/**
 * Body for PATCH /teams/{teamId}/priority.
 *
 * {@code priority} is null to unset (policy-level priority applies again),
 * otherwise an integer on the 1..10 queue scale (1=LOW, 5=NORMAL, 10=HIGH).
 */
public record UpdateTeamPriorityRequestDTO(Integer priority) {}
