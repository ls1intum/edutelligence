package de.tum.cit.aet.logos.logoswebservice.operations.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.operations.service.RequestLogStatsService;

@RestController
public class RequestLogStatsController {

    private final RequestLogStatsService requestLogStatsService;

    public RequestLogStatsController(RequestLogStatsService requestLogStatsService) {
        this.requestLogStatsService = requestLogStatsService;
    }

    @PostMapping("/logosdb/request_log_stats")
    public ResponseEntity<?> requestLogStats(@RequestAttribute("authContext") AuthContext auth,
                                             @RequestBody(required = false) Map<String, Object> body) {
        if (body == null) body = Map.of();
        String startDate    = (String) body.get("start_date");
        String endDate      = (String) body.get("end_date");
        int targetBuckets   = body.containsKey("target_buckets")
                ? ((Number) body.get("target_buckets")).intValue() : 120;
        // Absent means the whole platform, which is what this endpoint has
        // always returned — the scope is opt-in, so existing callers are
        // unaffected.
        Integer userId = body.get("user_id") instanceof Number n ? n.intValue() : null;
        Integer teamId = body.get("team_id") instanceof Number n ? n.intValue() : null;
        try {
            return ResponseEntity.ok(
                    requestLogStatsService.getRequestLogStats(startDate, endDate, targetBuckets, userId, teamId));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }
}
