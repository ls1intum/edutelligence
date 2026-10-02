package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ResponseStatusException;

/**
 * Maps gateway {@link ResponseStatusException}s to the orchestrator-shaped
 * {@code {"detail": "..."}} JSON body clients already expect.
 */
@RestControllerAdvice(basePackageClasses = InferenceGatewayController.class)
public class GatewayExceptionHandler {

    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<Map<String, String>> handle(ResponseStatusException ex) {
        String detail = ex.getReason() == null || ex.getReason().isBlank()
            ? ex.getStatusCode().toString()
            : ex.getReason();
        return ResponseEntity.status(ex.getStatusCode()).body(Map.of("detail", detail));
    }
}
