package de.tum.cit.aet.logos.logoswebservice.identity.dto;

/**
 * Body for PATCH /teams/{teamId}/public-stats.
 *
 * {@code share_public_stats} switches the team's successful requests into (or
 * out of) the unauthenticated public statistics page (GET /stats). The value
 * is required — the endpoint either shares the team or does not.
 */
public record UpdateTeamPublicStatsRequestDTO(Boolean share_public_stats) {}
