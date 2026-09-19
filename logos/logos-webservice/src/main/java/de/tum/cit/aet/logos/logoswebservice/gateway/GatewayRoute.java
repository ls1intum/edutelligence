package de.tum.cit.aet.logos.logoswebservice.gateway;

/**
 * Where the inference gateway should send the request.
 */
public enum GatewayRoute {
    /** Forward HTTP (incl. streaming) directly to the cloud provider. */
    CLOUD,
    /** Reverse-proxy to {@code logos.orchestrator.url}. */
    ORCHESTRATOR
}
