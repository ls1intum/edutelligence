package de.tum.cit.aet.logos.logoswebservice.identity.controller;

import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.ReplaceApplicationKeyQueueRanksRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.identity.service.ApplicationKeyQueueRankService;

/** Logos-admin ordered ranking of application keys across teams. */
@RestController
@RequestMapping("/admin")
public class ApplicationKeyQueueRankController {

    private final ApplicationKeyQueueRankService service;

    public ApplicationKeyQueueRankController(ApplicationKeyQueueRankService service) {
        this.service = service;
    }

    @GetMapping("/application-key-queue-ranks")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> listRanks() {
        return ResponseEntity.ok(service.listRanks());
    }

    @PutMapping("/application-key-queue-ranks")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> replaceRanks(
            @RequestBody ReplaceApplicationKeyQueueRanksRequestDTO body,
            @RequestAttribute("authContext") AuthContext auth) {
        return ResponseEntity.ok(service.replaceRanks(body, auth.userId()));
    }
}
