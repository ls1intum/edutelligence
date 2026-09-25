package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.Map;

/**
 * What a completed cloud forward reported about itself.
 *
 * @param usage        canonical token counts, empty when the response reported none
 * @param responseBody the response body to store, or {@code null} when the key
 *                     does not log payloads, the body was not retained, or it
 *                     streamed (a stream has no single body to store)
 */
public record GatewayForwardResult(Map<String, Long> usage, byte[] responseBody) {

    static GatewayForwardResult none() {
        return new GatewayForwardResult(Map.of(), null);
    }
}
