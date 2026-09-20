package de.tum.cit.aet.logos.logoswebservice.configuration.controller;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.annotation.JsonProperty;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelCapabilitiesUpdaterService;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.PriceUpdaterService;

@RestController
@RequestMapping("/internal")
public class InternalModelController {

    private final PriceUpdaterService priceUpdaterService;
    private final ModelCapabilitiesUpdaterService modelCapabilitiesUpdaterService;
    private final ModelRepository modelRepository;
    private final String internalSecret;

    public InternalModelController(
            PriceUpdaterService priceUpdaterService,
            ModelCapabilitiesUpdaterService modelCapabilitiesUpdaterService,
            ModelRepository modelRepository,
            @Value("${logos.orchestrator.internal-secret:}") String internalSecret) {
        this.priceUpdaterService = priceUpdaterService;
        this.modelCapabilitiesUpdaterService = modelCapabilitiesUpdaterService;
        this.modelRepository = modelRepository;
        this.internalSecret = internalSecret;
    }

    @PostMapping("/models_discovered")
    public ResponseEntity<?> modelsDiscovered(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestBody ModelDiscoveryRequest request) {
        if (internalSecret.isBlank() || authorization == null
                || !authorization.startsWith("Bearer ")
                || !MessageDigest.isEqual(
                    internalSecret.getBytes(StandardCharsets.UTF_8),
                    authorization.substring("Bearer ".length()).getBytes(StandardCharsets.UTF_8))) {
            return ResponseEntity.status(401).body(Map.of("error", "unauthorized"));
        }
        List<Integer> modelIds = request.modelIds() == null ? List.of() : request.modelIds();
        for (Integer modelId : modelIds) {
            if (modelId == null) continue;
            modelRepository.findById(modelId).ifPresent(model -> {
                priceUpdaterService.updatePricesForModelAsync(model.getId(), model.getName());
                modelCapabilitiesUpdaterService.updateCapabilitiesForModelAsync(model.getId(), model.getName());
            });
        }
        return ResponseEntity.ok(Map.of("status", "accepted"));
    }

    public record ModelDiscoveryRequest(@JsonProperty("model_ids") List<Integer> modelIds) {}
}
