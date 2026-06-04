package de.tum.cit.aet.logos.logoswebservice.identity.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.identity.service.MeService;

@RestController
public class MeController {

    private final MeService meService;

    public MeController(MeService meService) {
        this.meService = meService;
    }

    @GetMapping("/me")
    public ResponseEntity<?> getMe(@RequestAttribute("authContext") AuthContext auth) {
        if (auth.userId() == null) {
            return ResponseEntity.status(404).body(
                Map.of("detail", "No user linked to this key. Service keys cannot log into the UI.")
            );
        }
        return meService.getMe(auth.userId())
            .<ResponseEntity<?>>map(ResponseEntity::ok)
            .orElseGet(() -> ResponseEntity.status(404).body(
                Map.of("detail", "No user linked to this key. Service keys cannot log into the UI.")
            ));
    }
}
