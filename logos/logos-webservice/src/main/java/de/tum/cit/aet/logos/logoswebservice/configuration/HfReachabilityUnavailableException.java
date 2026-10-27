package de.tum.cit.aet.logos.logoswebservice.configuration;

/**
 * Raised when the Hugging Face precheck could not be performed (Hub
 * timeout, orchestrator unreachable): there is no verdict, so no vote is
 * recorded and the user is asked to try again.
 */
public class HfReachabilityUnavailableException extends RuntimeException {

    public HfReachabilityUnavailableException(String message) {
        super(message);
    }
}
