package de.tum.cit.aet.logos.logoswebservice.configuration;

/**
 * Raised when a vote is cast for a name that is already served by Logos,
 * as a model name or alias.
 */
public class ModelAlreadyAvailableException extends RuntimeException {

    public ModelAlreadyAvailableException(String message) {
        super(message);
    }
}
