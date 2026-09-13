package de.tum.cit.aet.logos.logoswebservice.operations.controller;

import java.io.IOException;
import java.util.Map;

import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.operations.service.BatchService;

/**
 * The batch page: upload a file, watch it run, download the results.
 *
 * Researchers mostly drive batches from a script, but somebody has to be able
 * to start one without writing code and to see where it got to — that is what
 * these endpoints are for. They are a thin forward to the orchestrator's Batch
 * API, called as the key the user picked, so the permission, ownership and
 * budget rules are the ones that apply to every other batch.
 */
@RestController
public class BatchController {

    private final BatchService batchService;

    public BatchController(BatchService batchService) {
        this.batchService = batchService;
    }

    /** The user's keys, for the picker: a batch runs as exactly one of them. */
    @GetMapping("/logosdb/batches/keys")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "', '"
        + Role.Names.APP_DEVELOPER + "')")
    public ResponseEntity<?> keys(@RequestAttribute("authContext") AuthContext auth) {
        if (auth.userId() == null) {
            return ResponseEntity.status(403).body(Map.of("detail", "No user context"));
        }
        return ResponseEntity.ok(batchService.keysForUser(auth.userId()));
    }

    @GetMapping("/logosdb/batches")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "', '"
        + Role.Names.APP_DEVELOPER + "')")
    public ResponseEntity<?> list(@RequestParam("apiKeyId") int apiKeyId,
                                  @RequestAttribute("authContext") AuthContext auth) {
        return proxy(() -> batchService.listBatches(requireUser(auth), apiKeyId));
    }

    @GetMapping("/logosdb/batches/{batchId}")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "', '"
        + Role.Names.APP_DEVELOPER + "')")
    public ResponseEntity<?> get(@PathVariable String batchId,
                                 @RequestParam("apiKeyId") int apiKeyId,
                                 @RequestAttribute("authContext") AuthContext auth) {
        return proxy(() -> batchService.getBatch(requireUser(auth), apiKeyId, batchId));
    }

    @PostMapping("/logosdb/batches/{batchId}/cancel")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "', '"
        + Role.Names.APP_DEVELOPER + "')")
    public ResponseEntity<?> cancel(@PathVariable String batchId,
                                    @RequestParam("apiKeyId") int apiKeyId,
                                    @RequestAttribute("authContext") AuthContext auth) {
        return proxy(() -> batchService.cancelBatch(requireUser(auth), apiKeyId, batchId));
    }

    /**
     * Download a finished batch's results.
     *
     * The file id comes from the batch object the caller just read; the
     * orchestrator refuses one their team does not own, so this cannot be used
     * to fish for other teams' output.
     */
    @GetMapping("/logosdb/batches/{batchId}/results")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "', '"
        + Role.Names.APP_DEVELOPER + "')")
    public ResponseEntity<?> results(@PathVariable String batchId,
                                     @RequestParam("apiKeyId") int apiKeyId,
                                     @RequestParam("outputFileId") String outputFileId,
                                     @RequestAttribute("authContext") AuthContext auth) {
        return proxy(() -> batchService.batchResults(requireUser(auth), apiKeyId, outputFileId),
            "attachment; filename=\"" + batchId + "_results.jsonl\"");
    }

    @PostMapping(value = "/logosdb/batches", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "', '"
        + Role.Names.APP_DEVELOPER + "')")
    public ResponseEntity<?> create(@RequestParam("file") MultipartFile file,
                                    @RequestParam("apiKeyId") int apiKeyId,
                                    @RequestParam(value = "endpoint", required = false) String endpoint,
                                    @RequestParam(value = "completionWindow", required = false) String window,
                                    @RequestParam(value = "execution", required = false) String execution,
                                    @RequestAttribute("authContext") AuthContext auth) {
        if (file == null || file.isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("detail", "A batch needs a .jsonl file."));
        }
        byte[] content;
        try {
            content = file.getBytes();
        } catch (IOException exc) {
            return ResponseEntity.badRequest().body(Map.of("detail", "The upload could not be read."));
        }
        return proxy(() -> batchService.createBatch(requireUser(auth), apiKeyId,
            file.getOriginalFilename(), content, endpoint, window, execution));
    }

    private int requireUser(AuthContext auth) {
        if (auth.userId() == null) {
            throw new BatchService.KeyNotOwnedException("No user context");
        }
        return auth.userId();
    }

    private ResponseEntity<?> proxy(java.util.function.Supplier<BatchService.ProxiedResponse> call) {
        return proxy(call, null);
    }

    private ResponseEntity<?> proxy(java.util.function.Supplier<BatchService.ProxiedResponse> call,
                                    String contentDisposition) {
        try {
            BatchService.ProxiedResponse response = call.get();
            ResponseEntity.BodyBuilder builder = ResponseEntity.status(response.status());
            if (response.contentType() != null) {
                builder = builder.header("Content-Type", response.contentType());
            }
            if (contentDisposition != null) {
                builder = builder.header("Content-Disposition", contentDisposition);
            }
            return builder.body(response.body());
        } catch (BatchService.KeyNotOwnedException exc) {
            return ResponseEntity.status(403).body(Map.of("detail", exc.getMessage()));
        } catch (BatchService.CredentialExchangeException exc) {
            // The key is fine and owned; what failed is the exchange with the
            // orchestrator — a deployment problem, not the caller's.
            return ResponseEntity.status(502).body(Map.of("detail", exc.getMessage()));
        }
    }
}
