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
 * <p>The end of the delivery to the client is not one of them: a slow client
 * keeps the relay busy after the upstream has finished, which is neither
 * Logos' nor the provider's time and is stored as the response timestamp of
 * the row instead.
 *
 * @param providerCall     the request is handed to the upstream; null when it never was
 * @param firstToken       the first token arrived from the upstream: the first
 *                         streamed event that carries content, or the start of a
 *                         JSON body, which has no tokens in flight and stands in
 *                         for it; null when no body byte arrived
 * @param providerResponse the upstream finished sending, excluding time the relay
 *                         spent blocked on writes to the client; on a failed call,
 *                         when the call failed
 */
public record GatewayForwardTimings(Instant providerCall, Instant firstToken, Instant providerResponse) {

    static final GatewayForwardTimings NONE = new GatewayForwardTimings(null, null, null);
}
