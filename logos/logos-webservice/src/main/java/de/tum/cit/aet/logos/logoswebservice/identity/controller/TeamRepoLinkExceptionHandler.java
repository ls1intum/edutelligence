package de.tum.cit.aet.logos.logoswebservice.identity.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ResponseStatusException;

/**
 * Maps repository-link {@link ResponseStatusException}s to the
 * {@code {"detail": "..."}} body the UI's {@code extractDetail()} reads.
 * Scoped to this controller so gateway and other packages keep their own
 * handlers.
 */
@RestControllerAdvice(assignableTypes = TeamRepoLinkController.class)
public class TeamRepoLinkExceptionHandler {

    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<Map<String, String>> handle(ResponseStatusException ex) {
        String detail = ex.getReason() == null || ex.getReason().isBlank()
            ? ex.getStatusCode().toString()
            : ex.getReason();
        return ResponseEntity.status(ex.getStatusCode()).body(Map.of("detail", detail));
    }
}
