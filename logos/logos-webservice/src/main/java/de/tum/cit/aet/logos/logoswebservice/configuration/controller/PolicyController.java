package de.tum.cit.aet.logos.logoswebservice.configuration.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.AddPolicyRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.DeletePolicyRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.GetPolicyRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.UpdatePolicyRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.PolicyService;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;

@RestController
@RequestMapping("/logosdb")
public class PolicyController {

    private final PolicyService policyService;

    public PolicyController(PolicyService policyService) {
        this.policyService = policyService;
    }

    @PostMapping("/get_policies")
    public ResponseEntity<?> getPolicies(@RequestAttribute("authContext") AuthContext auth) {
        return ResponseEntity.ok(policyService.getPolicies(auth.keyValue()));
    }

    @PostMapping("/add_policy")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> addPolicy(@RequestBody AddPolicyRequestDTO req) {
        return ResponseEntity.ok(policyService.addPolicy(
            req.name(),
            req.description() != null ? req.description() : "",
            req.thresholdPrivacy() != null ? req.thresholdPrivacy() : "LOCAL",
            req.thresholdLatency() != null ? req.thresholdLatency() : 0,
            req.thresholdAccuracy() != null ? req.thresholdAccuracy() : 0,
            req.thresholdCost() != null ? req.thresholdCost() : 0,
            req.thresholdQuality() != null ? req.thresholdQuality() : 0,
            req.priority() != null ? req.priority() : 0,
            req.topic() != null ? req.topic() : "",
            req.apiKeyId(),
            req.teamId()));
    }

    @PostMapping("/update_policy")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> updatePolicy(@RequestBody UpdatePolicyRequestDTO req) {
        return ResponseEntity.ok(policyService.updatePolicy(
            req.id() != null ? req.id() : 0,
            req.name(),
            req.description() != null ? req.description() : "",
            req.thresholdPrivacy() != null ? req.thresholdPrivacy() : "LOCAL",
            req.thresholdLatency() != null ? req.thresholdLatency() : 0,
            req.thresholdAccuracy() != null ? req.thresholdAccuracy() : 0,
            req.thresholdCost() != null ? req.thresholdCost() : 0,
            req.thresholdQuality() != null ? req.thresholdQuality() : 0,
            req.priority() != null ? req.priority() : 0,
            req.topic() != null ? req.topic() : "",
            req.apiKeyId(),
            req.teamId()));
    }

    @PostMapping("/delete_policy")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> deletePolicy(@RequestBody DeletePolicyRequestDTO req) {
        return ResponseEntity.ok(policyService.deletePolicy(req.id() != null ? req.id() : 0));
    }

    @PostMapping("/get_policy")
    public ResponseEntity<?> getPolicy(@RequestAttribute("authContext") AuthContext auth,
                                        @RequestBody GetPolicyRequestDTO req) {
        return policyService.getPolicy(req.policyId() != null ? req.policyId() : 0, auth.keyValue())
                .<ResponseEntity<?>>map(ResponseEntity::ok)
                .orElse(ResponseEntity.status(404).body(Map.of("error", "Not Found")));
    }
}
