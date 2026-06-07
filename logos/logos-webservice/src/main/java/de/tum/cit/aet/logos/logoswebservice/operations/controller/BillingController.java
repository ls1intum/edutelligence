package de.tum.cit.aet.logos.logoswebservice.operations.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.admin.service.ApiKeyAdminService;
import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.operations.service.BillingService;

@RestController
public class BillingController {

    private final BillingService billingService;
    private final ApiKeyAdminService apiKeyAdminService;

    public BillingController(BillingService billingService, ApiKeyAdminService apiKeyAdminService) {
        this.billingService = billingService;
        this.apiKeyAdminService = apiKeyAdminService;
    }

    @PostMapping("/logosdb/add_billing")
    public ResponseEntity<?> addBilling(@RequestAttribute("authContext") AuthContext auth,
                                        @RequestBody Map<String, Object> body) {
        if (!"logos_admin".equals(auth.role())) {
            return ResponseEntity.status(403).body(Map.of("error", "logos_admin required"));
        }
        String typeName  = (String) body.get("type_name");
        double typeCost  = ((Number) body.get("type_cost")).doubleValue();
        String validFrom = (String) body.get("valid_from");
        Integer modelId  = body.containsKey("model_id") && body.get("model_id") != null
                ? ((Number) body.get("model_id")).intValue() : null;
        try {
            return ResponseEntity.ok(billingService.addBilling(typeName, typeCost, validFrom, modelId));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.internalServerError().body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/logosdb/billing/team_budget_history")
    public ResponseEntity<?> teamBudgetHistory(@RequestAttribute("authContext") AuthContext auth,
                                               @RequestBody Map<String, Object> body) {
        if (!"logos_admin".equals(auth.role())) {
            return ResponseEntity.status(403).body(Map.of("error", "logos_admin required"));
        }
        String startIso = (String) body.get("start_iso");
        String endIso   = (String) body.get("end_iso");
        return ResponseEntity.ok(billingService.getTeamBudgetHistory(startIso, endIso));
    }

    @PostMapping("/logosdb/billing/key_budget_history/{teamId}")
    public ResponseEntity<?> keyBudgetHistory(@RequestAttribute("authContext") AuthContext auth,
                                              @PathVariable int teamId,
                                              @RequestBody Map<String, Object> body) {
        boolean isLogosAdmin = "logos_admin".equals(auth.role());
        boolean isTeamOwner = "app_admin".equals(auth.role())
                && auth.userId() != null
                && apiKeyAdminService.isTeamOwner(teamId, auth.userId());
        if (!isLogosAdmin && !isTeamOwner) {
            return ResponseEntity.status(403).body(Map.of("error", "logos_admin or team owner required"));
        }
        String startIso = (String) body.get("start_iso");
        String endIso   = (String) body.get("end_iso");
        return ResponseEntity.ok(billingService.getKeyBudgetHistory(teamId, startIso, endIso));
    }
}