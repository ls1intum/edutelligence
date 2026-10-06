package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.Locale;
import java.util.Set;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Component;

import jakarta.servlet.http.HttpServletRequest;

/**
 * Parses {@code X-Logos-SLA} / {@code X-Logos-Workflow-Tag} and resolves a
 * matching workflow step (or workflow) for the caller's team.
 */
@Component
public class GatewayWorkflowAttributionResolver {

    private static final Set<String> VALID_SLAS =
        Set.of("ux-critical", "ux-high-prio", "ux-background");

    private final NamedParameterJdbcTemplate jdbc;

    public GatewayWorkflowAttributionResolver(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public GatewayRequestAttribution resolve(HttpServletRequest request, Integer teamId) {
        String headerSla = firstHeader(request, "X-Logos-SLA", "logos-sla");
        String requestSla = normalizeSla(headerSla);
        String tag = firstHeader(request, "X-Logos-Workflow-Tag", "logos-workflow-tag");
        if (tag == null || tag.isBlank() || teamId == null) {
            return new GatewayRequestAttribution(null, null, null, requestSla);
        }
        String normalizedTag = tag.trim();
        MapSqlParameterSource params = new MapSqlParameterSource()
            .addValue("tag", normalizedTag)
            .addValue("team_id", teamId);
        var step = jdbc.query("""
            SELECT s.id AS step_id, s.workflow_id,
                   COALESCE(s.confirmed_sla, s.recommended_sla) AS sla
              FROM ai_workflow_steps s
              JOIN ai_workflows w ON w.id = s.workflow_id
              JOIN ai_workflow_analyses a ON a.id = w.analysis_id
             WHERE s.tag = :tag
               AND a.team_id = :team_id
               AND w.deleted_at IS NULL
               AND w.status <> 'ignored'
             ORDER BY s.id
             LIMIT 1
            """, params, (rs, rowNum) -> new GatewayRequestAttribution(
                normalizedTag,
                rs.getInt("workflow_id"),
                rs.getInt("step_id"),
                requestSla != null ? requestSla : normalizeSla(rs.getString("sla"))
            ));
        if (!step.isEmpty()) {
            return step.getFirst();
        }
        var workflow = jdbc.query("""
            SELECT w.id AS workflow_id
              FROM ai_workflows w
              JOIN ai_workflow_analyses a ON a.id = w.analysis_id
             WHERE w.tag = :tag
               AND a.team_id = :team_id
               AND w.deleted_at IS NULL
               AND w.status <> 'ignored'
             ORDER BY w.id
             LIMIT 1
            """, params, (rs, rowNum) -> new GatewayRequestAttribution(
                normalizedTag,
                rs.getInt("workflow_id"),
                null,
                requestSla
            ));
        if (!workflow.isEmpty()) {
            return workflow.getFirst();
        }
        return new GatewayRequestAttribution(normalizedTag, null, null, requestSla);
    }

    private static String normalizeSla(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        String sla = raw.trim().toLowerCase(Locale.ROOT);
        return VALID_SLAS.contains(sla) ? sla : null;
    }

    private static String firstHeader(HttpServletRequest request, String... names) {
        for (String name : names) {
            String value = request.getHeader(name);
            if (value != null && !value.isBlank()) {
                return value.trim();
            }
        }
        return null;
    }
}
