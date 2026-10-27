package de.tum.cit.aet.logos.logoswebservice.configuration;

/**
 * Raised when the Hugging Face precheck reports the repository as not
 * found or not visible to the central HF_TOKEN for a reason other than
 * gating (a gated repository is a legitimate request — it only needs a
 * license acceptance first): the model cannot be requested.
 */
public class ModelNotOnHuggingFaceException extends RuntimeException {

    public ModelNotOnHuggingFaceException(String message) {
        super(message);
    }
}
