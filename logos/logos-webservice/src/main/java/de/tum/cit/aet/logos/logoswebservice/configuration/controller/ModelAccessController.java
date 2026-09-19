package de.tum.cit.aet.logos.logoswebservice.configuration.controller;

import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.configuration.dto.ModelAccessResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelAccessService;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;

/**
 * Read-only views across the two independent permission dimensions (model,
 * provider). Granting stays on the team/key detail pages; this answers the
 * question those views cannot: for one model, who actually has both the
 * model grant and a grant for a provider that hosts it.
 */
@RestController
@RequestMapping("/admin")
public class ModelAccessController {

    private final ModelAccessService modelAccessService;

    public ModelAccessController(ModelAccessService modelAccessService) {
        this.modelAccessService = modelAccessService;
    }

    @GetMapping("/models/{modelId}/access")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<ModelAccessResponseDTO> getModelAccess(@PathVariable Integer modelId) {
        return ResponseEntity.ok(modelAccessService.getModelAccess(modelId));
    }
}
