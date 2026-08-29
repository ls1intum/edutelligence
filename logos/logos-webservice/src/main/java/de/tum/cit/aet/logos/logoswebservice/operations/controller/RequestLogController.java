package de.tum.cit.aet.logos.logoswebservice.operations.controller;

import java.util.List;
import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
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

    /**
     * System-wide request feed. Unlike {@code /request_logs} this has no
     * per-user scoping to fall back on — every row carries the requester's full
     * name, team and cloud cost — so it is restricted to Logos admins.
     *
     * <p>The statistics page gets its newest unfiltered rows pushed over
     * {@code /ws/stats/v2} and calls this for everything else: paging back
     * through the range, and any view narrowed to one requester or team. Pages
     * are keyset-based — pass the {@code next_cursor} of the previous response
     * as {@code cursor_ts}/{@code cursor_id}. Without a body the service returns
     * the newest page of the last 30 days.
     */
    @PostMapping("/latest_requests")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> latestRequests(@RequestAttribute("authContext") AuthContext auth,
                                            @RequestBody(required = false) Map<String, Object> body) {
        if (body == null) body = Map.of();
        String start = body.get("start") instanceof String s ? s : null;
        String end = body.get("end") instanceof String s ? s : null;
        Integer userId = body.get("user_id") instanceof Number n ? n.intValue() : null;
        Integer teamId = body.get("team_id") instanceof Number n ? n.intValue() : null;
        // The feed's state bucket; absent means all states. A supplied value
        // that names none of the four buckets matches no rows — the same
        // fail-closed answer an unknown user_id gives. Blank and non-string
        // values collapse to the all-states sentinel on purpose, mirroring the
        // client's normalizeFeedStatus: a picker that stopped showing
        // everything reads as broken, so the feed widens instead.
        String status = body.get("status") instanceof String s && !s.isBlank() ? s : null;
        String cursorTs = body.get("cursor_ts") instanceof String s ? s : null;
        String cursorId = body.get("cursor_id") instanceof String s ? s : null;
        int limit = body.get("limit") instanceof Number n
            ? n.intValue() : RequestLogService.LATEST_REQUESTS_PAGE_SIZE;
        return ResponseEntity.ok(requestLogService.getLatestRequests(
            start, end, userId, teamId, status, cursorTs, cursorId, limit, true));
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
}
