package de.tum.cit.aet.logos.logoswebservice.common;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Configuration for the per-IP rate limits on endpoints that take no valid credential:
 * public endpoints (e.g. {@code /info}) and the failure path of API-key authentication
 * (e.g. {@code /logosdb/get_model_health}). Defaults live in application.properties.
 */
@ConfigurationProperties(prefix = "logos.rate-limiting")
public record RateLimitingProperties(boolean enabled, int publicEndpointRequestsPerMinute, int authFailureRequestsPerMinute) {
}
