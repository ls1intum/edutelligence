package de.tum.cit.aet.logos.logoswebservice.operations.controller;

import java.util.List;
import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.operations.service.RequestLogService;

@RestController
@RequestMapping("/logosdb")
public class RequestLogController {

    private final RequestLogService requestLogService;

    public RequestLogController(RequestLogService requestLogService) {
        this.requestLogService = requestLogService;
    }

    @PostMapping("/latest_requests")
    public ResponseEntity<?> latestRequests(@RequestAttribute("authContext") AuthContext auth) {
        return ResponseEntity.ok(requestLogService.getLatestRequests());
    }

    @PostMapping("/request_logs")
    public ResponseEntity<?> requestLogs(@RequestAttribute("authContext") AuthContext auth,
                                         @RequestBody Map<String, Object> body) {
        Object rawIds = body.get("request_ids");
        if (!(rawIds instanceof List)) {
            return ResponseEntity.badRequest().body(Map.of("error", "request_ids must be a list of strings"));
        }
        @SuppressWarnings("unchecked")
        List<Object> ids = (List<Object>) rawIds;
        for (Object id : ids) {
            if (!(id instanceof String)) {
                return ResponseEntity.badRequest().body(Map.of("error", "request_ids must be a list of strings"));
            }
        }
        List<String> requestIds = ids.stream()
                .map(Object::toString)
                .filter(s -> !s.isBlank())
                .distinct()
                .toList();
        // Admins see request history across the whole system; non-admin callers
        // see only requests they themselves made (across all their api keys).
        Integer userId = Role.LOGOS_ADMIN.matches(auth.role()) ? null : auth.userId();
        return ResponseEntity.ok(requestLogService.getRequestLogs(userId, requestIds));
    }

    @PostMapping("/paginated_requests")
    public ResponseEntity<?> paginatedRequests(@RequestAttribute("authContext") AuthContext auth,
                                               @RequestBody(required = false) Map<String, Object> body) {
        if (body == null) body = Map.of();
        int page = body.containsKey("page") ? ((Number) body.get("page")).intValue() : 1;
        int perPage = body.containsKey("per_page") ? ((Number) body.get("per_page")).intValue() : 20;
        // Admins see the request history across all users — the statistics page
        // already streams every request live, so the paginated history must not
        // be limited to requests made by the admin themselves.
        Integer userId = Role.LOGOS_ADMIN.matches(auth.role()) ? null : auth.userId();
        return ResponseEntity.ok(requestLogService.getPaginatedRequests(userId, page, perPage));
    }
}
