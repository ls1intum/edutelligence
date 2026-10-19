package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.time.Instant;

/**
 * The instants a cloud forward passed through, as seen by this process.
 *
 * <p>They split a request's wall time the way the statistics page reads it:
 * everything before {@code providerCall} is time spent in Logos (key lookup,
 * rate limit, budget check, waiting for a database connection), and
 * {@code providerCall} to {@code providerResponse} is the provider's own time.
 *
 * @param providerCall     the request is handed to the upstream; null when it never was
 * @param firstByte        the first response body byte arrived from the upstream
 *                         (the first streamed event, or the start of a JSON body);
 *                         null when no body byte arrived
 * @param providerResponse the upstream response ended; null when it never started
 */
public record GatewayForwardTimings(Instant providerCall, Instant firstByte, Instant providerResponse) {

    static final GatewayForwardTimings NONE = new GatewayForwardTimings(null, null, null);
}
