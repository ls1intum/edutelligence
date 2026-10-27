package de.tum.cit.aet.logos.logoswebservice.configuration;

/**
 * Raised when the Hugging Face precheck reports the repository as not
 * found or not visible to the central HF_TOKEN: it is not a model that
 * can be requested.
 */
public class ModelNotOnHuggingFaceException extends RuntimeException {

    public ModelNotOnHuggingFaceException(String message) {
        super(message);
    }
}
