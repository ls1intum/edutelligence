package de.tum.cit.aet.logos.logoswebservice.configuration.controller;

import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import de.tum.cit.aet.logos.logoswebservice.configuration.HfReachabilityUnavailableException;
import de.tum.cit.aet.logos.logoswebservice.configuration.ModelAlreadyAvailableException;
import de.tum.cit.aet.logos.logoswebservice.configuration.ModelNotOnHuggingFaceException;

/**
 * Maps the model-request voting outcomes to HTTP responses:
 * {@code ModelAlreadyAvailableException} to 409 (the name is already served
 * by Logos), {@code ModelNotOnHuggingFaceException} to 400 (the Hugging Face
 * precheck did not find the repository), and
 * {@code HfReachabilityUnavailableException} to 503 (the precheck timed out;
 * the user should retry). Invalid names need no handler here: the global
 * handler already maps their {@link IllegalArgumentException} to 400.
 *
 * Scoped to {@link ModelRequestController} so the other configuration
 * endpoints keep their own behavior.
 */
@RestControllerAdvice(assignableTypes = ModelRequestController.class)
public class ModelRequestExceptionHandler {

    @ExceptionHandler(ModelAlreadyAvailableException.class)
    public ResponseEntity<Map<String, String>> handleAlreadyAvailable(ModelAlreadyAvailableException ex) {
        return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of("error", ex.getMessage()));
    }

    @ExceptionHandler(ModelNotOnHuggingFaceException.class)
    public ResponseEntity<Map<String, String>> handleNotOnHuggingFace(ModelNotOnHuggingFaceException ex) {
        return ResponseEntity.badRequest().body(Map.of("error", ex.getMessage()));
    }

    @ExceptionHandler(HfReachabilityUnavailableException.class)
    public ResponseEntity<Map<String, String>> handleHfUnavailable(HfReachabilityUnavailableException ex) {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body(Map.of("error", ex.getMessage()));
    }
}
