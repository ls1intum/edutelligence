package de.tum.cit.aet.logos.logoswebservice.operations.controller;

import java.io.IOException;
import java.io.OutputStream;
import java.util.Map;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.identity.service.ApiKeyAdminService;
import de.tum.cit.aet.logos.logoswebservice.operations.service.TeamActivityService;

/**
 * One team's live request counts and token spend.
 *
 * App administrators wanted what the statistics page gives Logos admins,
 * narrowed to their own teams and cut down to the two questions they actually
 * ask: what is running right now, and what has the team used.
 */
@RestController
public class TeamActivityController {

    private static final Logger log = LoggerFactory.getLogger(TeamActivityController.class);

    private final TeamActivityService teamActivityService;
    private final ApiKeyAdminService apiKeyAdminService;
    private final ObjectMapper objectMapper;

    public TeamActivityController(TeamActivityService teamActivityService,
                                  ApiKeyAdminService apiKeyAdminService,
                                  ObjectMapper objectMapper) {
        this.teamActivityService = teamActivityService;
        this.apiKeyAdminService = apiKeyAdminService;
        this.objectMapper = objectMapper;
    }

    /**
     * Activity for one team.
     *
     * Team id comes from the path and the check is against that id, so there is
     * no way to widen the scope through the body — the same ownership rule the
     * key admin endpoints apply: a Logos admin sees any team, an app admin only
     * one they own.
     */
    @PostMapping("/logosdb/teams/{teamId}/activity")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public ResponseEntity<?> teamActivity(@PathVariable Integer teamId,
                                          @RequestBody(required = false) Map<String, Object> body,
                                          @RequestAttribute("authContext") AuthContext auth) {
        if (teamId == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "team_id is required"));
        }
        if (Role.APP_ADMIN.matches(auth.role())
                && (auth.userId() == null || !apiKeyAdminService.isTeamOwner(teamId, auth.userId()))) {
            return ResponseEntity.status(403).body(Map.of("detail", "Team owner access required"));
        }
        Map<String, Object> payload = body != null ? body : Map.of();
        Integer days = payload.get("days") instanceof Number n ? n.intValue() : null;
        // Narrows the request list to one requester. The team scope still
        // applies on top, so this can only ever cut the list down further —
        // there is no user id that reaches outside the team checked above.
        Integer userId = payload.get("user_id") instanceof Number n ? n.intValue() : null;
        String cursorTs = payload.get("cursor_ts") instanceof String s ? s : null;
        String cursorId = payload.get("cursor_id") instanceof String s ? s : null;
        return ResponseEntity.ok(
            teamActivityService.getTeamActivity(teamId, days, userId, cursorTs, cursorId));
    }

    /**
     * Download of the team's request traces, as a file.
     *
     * Every request of the window comes back, the same slice the activity
     * view shows. The consented ones (recorded at FULL privacy) carry their
     * request and response content; for the billing-only rows the content
     * columns are empty, and the file says whether the team has full logging
     * activated at all. Same gate as the activity view, same window and
     * narrowing rules, so the export never reaches further than the page it
     * is started from.
     *
     * The answer is a streamed download, not a JSON body: the file is
     * written row by row as it is read, and the browser saves it instead of
     * the application parsing it. Everything the caller needs to know about
     * the file before the first byte — its size, whether it is the whole
     * answer — goes out as response headers, and the JSON file carries the
     * same facts in itself for whoever opens it later.
     *
     * A window that outruns one file continues rather than truncating into
     * silence: the body may carry {@code cursor}, the opaque token an
     * earlier download handed back as {@code X-Logos-Export-Next-Cursor}
     * (window, slice tail, team and requester in one), and the answer then
     * holds the next, older slice over the very window the walk started in
     * — its headers and, in the JSON file, {@code next_cursor} describing
     * the rest the same way. A token the service never issued, or one that
     * names a window beyond the limits a fresh export obeys, is a 400:
     * answering it would re-cut the first slice and read as duplicated rows.
     */
    @PostMapping("/logosdb/teams/{teamId}/activity/export")
    @PreAuthorize("hasAnyAuthority('" + Role.Names.LOGOS_ADMIN + "', '" + Role.Names.APP_ADMIN + "')")
    public void exportTeamTraces(@PathVariable Integer teamId,
                                 @RequestBody(required = false) Map<String, Object> body,
                                 @RequestAttribute("authContext") AuthContext auth,
                                 HttpServletResponse response) {
        if (teamId == null) {
            writeJsonError(response, 400, "error", "team_id is required");
            return;
        }
        if (Role.APP_ADMIN.matches(auth.role())
                && (auth.userId() == null || !apiKeyAdminService.isTeamOwner(teamId, auth.userId()))) {
            writeJsonError(response, 403, "detail", "Team owner access required");
            return;
        }
        Map<String, Object> payload = body != null ? body : Map.of();
        Integer days = payload.get("days") instanceof Number n ? n.intValue() : null;
        Integer userId = payload.get("user_id") instanceof Number n ? n.intValue() : null;
        String format = payload.get("format") instanceof String s ? s : null;
        String cursor = payload.get("cursor") instanceof String s ? s : null;

        TeamActivityService.ExportPrep prep;
        try {
            prep = teamActivityService.prepareExport(teamId, days, userId, format, cursor);
        } catch (IllegalArgumentException e) {
            writeJsonError(response, 400, "error", "Malformed export cursor");
            return;
        }
        response.setContentType(prep.format() == TeamActivityService.ExportFormat.CSV
            ? "text/csv; charset=utf-8"
            : "application/json");
        response.setHeader(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + prep.fileName() + "\"");
        response.setHeader("X-Logos-Export-Total", String.valueOf(prep.totalInWindow()));
        response.setHeader("X-Logos-Export-Truncated", String.valueOf(prep.truncated()));
        response.setHeader("X-Logos-Export-Count", String.valueOf(prep.count()));
        String cursorToken = prep.cursorToken();
        if (cursorToken != null) {
            response.setHeader("X-Logos-Export-Next-Cursor", cursorToken);
        }
        try (OutputStream out = response.getOutputStream()) {
            teamActivityService.writeExportFile(prep, out);
            out.flush();
        } catch (IOException e) {
            // The download is a stream: once the first bytes are out the
            // answer cannot be retracted, so a reader that goes away mid-file
            // is logged rather than answered.
            log.warn("Trace export for team {} interrupted: {}", teamId, e.toString());
        }
    }

    private void writeJsonError(HttpServletResponse response, int status, String field, String message) {
        try {
            response.setStatus(status);
            response.setContentType("application/json");
            response.getWriter().write(objectMapper.writeValueAsString(Map.of(field, message)));
        } catch (IOException e) {
            log.warn("Could not write the export error response: {}", e.toString());
        }
    }
}
