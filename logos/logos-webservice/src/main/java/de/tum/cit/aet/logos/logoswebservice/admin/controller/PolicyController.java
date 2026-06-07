package de.tum.cit.aet.logos.logoswebservice.admin.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.admin.service.PolicyService;
import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;

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
    public ResponseEntity<?> addPolicy(@RequestAttribute("authContext") AuthContext auth,
                                        @RequestBody Map<String, Object> body) {
        if (!"logos_admin".equals(auth.role())) return forbidden();
        String name = (String) body.get("name");
        String description = (String) body.getOrDefault("description", "");
        String privacy = (String) body.getOrDefault("threshold_privacy", "LOCAL");
        int latency = toInt(body.get("threshold_latency"), 0);
        int accuracy = toInt(body.get("threshold_accuracy"), 0);
        int cost = toInt(body.get("threshold_cost"), 0);
        int quality = toInt(body.get("threshold_quality"), 0);
        int priority = toInt(body.get("priority"), 0);
        String topic = (String) body.getOrDefault("topic", "");
        Integer apiKeyId = body.get("api_key_id") != null ? toInt(body.get("api_key_id"), 0) : null;
        Integer teamId = body.get("team_id") != null ? toInt(body.get("team_id"), 0) : null;
        return ResponseEntity.ok(policyService.addPolicy(name, description, privacy,
                latency, accuracy, cost, quality, priority, topic, apiKeyId, teamId));
    }

    @PostMapping("/update_policy")
    public ResponseEntity<?> updatePolicy(@RequestAttribute("authContext") AuthContext auth,
                                           @RequestBody Map<String, Object> body) {
        if (!"logos_admin".equals(auth.role())) return forbidden();
        int id                  = toInt(body.get("id"), 0);
        String name             = (String) body.get("name");
        String description      = (String) body.getOrDefault("description", "");
        String privacy          = (String) body.getOrDefault("threshold_privacy", "LOCAL");
        int latency             = toInt(body.get("threshold_latency"), 0);
        int accuracy            = toInt(body.get("threshold_accuracy"), 0);
        int cost                = toInt(body.get("threshold_cost"), 0);
        int quality             = toInt(body.get("threshold_quality"), 0);
        int priority            = toInt(body.get("priority"), 0);
        String topic            = (String) body.getOrDefault("topic", "");
        Integer apiKeyId        = body.get("api_key_id") != null ? toInt(body.get("api_key_id"), 0) : null;
        Integer teamId          = body.get("team_id")    != null ? toInt(body.get("team_id"),    0) : null;
        return ResponseEntity.ok(policyService.updatePolicy(id, name, description, privacy,
                latency, accuracy, cost, quality, priority, topic, apiKeyId, teamId));
    }

    @PostMapping("/delete_policy")
    public ResponseEntity<?> deletePolicy(@RequestAttribute("authContext") AuthContext auth,
                                           @RequestBody Map<String, Object> body) {
        if (!"logos_admin".equals(auth.role())) return forbidden();
        int id = toInt(body.get("id"), 0);
        return ResponseEntity.ok(policyService.deletePolicy(id));
    }

    @PostMapping("/get_policy")
    public ResponseEntity<?> getPolicy(@RequestAttribute("authContext") AuthContext auth,
                                        @RequestBody Map<String, Object> body) {
        int policyId = toInt(body.get("policy_id"), 0);
        return policyService.getPolicy(policyId, auth.keyValue())
                .<ResponseEntity<?>>map(ResponseEntity::ok)
                .orElse(ResponseEntity.status(404).body(Map.of("error", "Not Found")));
    }

    private static ResponseEntity<?> forbidden() {
        return ResponseEntity.status(403).body(Map.of("detail", "logos_admin required"));
    }

    private static int toInt(Object v, int def) {
        if (v instanceof Number n) return n.intValue();
        return def;
    }
}