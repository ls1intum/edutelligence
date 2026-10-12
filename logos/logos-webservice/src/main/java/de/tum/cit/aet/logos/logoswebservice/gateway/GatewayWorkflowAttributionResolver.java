package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.Locale;
import java.util.Set;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Component;

import jakarta.servlet.http.HttpServletRequest;

/**
 * Parses {@code X-Logos-SLO} / {@code X-Logos-Workflow-Tag} and resolves a
 * matching workflow step (or workflow) for the caller's team. Only each
 * repository's latest succeeded analysis counts, so ignoring, deleting, or
 * renaming a tag is not undone by a superseded copy.
 */
@Component
public class GatewayWorkflowAttributionResolver {

    private static final Set<String> VALID_SLOS =
        Set.of("ux-critical", "ux-high-prio", "ux-background");

    private final NamedParameterJdbcTemplate jdbc;

    public GatewayWorkflowAttributionResolver(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public GatewayRequestAttribution resolve(HttpServletRequest request, Integer teamId) {
        String headerSlo = firstHeader(request, "X-Logos-SLO", "logos-slo");
        String requestSlo = normalizeSlo(headerSlo);
        String tag = firstHeader(request, "X-Logos-Workflow-Tag", "logos-workflow-tag");
        if (tag == null || tag.isBlank() || teamId == null) {
            return new GatewayRequestAttribution(null, null, null, requestSlo);
        }
        String normalizedTag = tag.trim();
        MapSqlParameterSource params = new MapSqlParameterSource()
            .addValue("tag", normalizedTag)
            .addValue("team_id", teamId);
        var step = jdbc.query("""
            SELECT s.id AS step_id, s.workflow_id,
                   COALESCE(s.confirmed_slo, s.recommended_slo) AS slo
              FROM ai_workflow_steps s
              JOIN ai_workflows w ON w.id = s.workflow_id
              JOIN ai_workflow_analyses a ON a.id = w.analysis_id
             WHERE s.tag = :tag
               AND a.team_id = :team_id
               AND a.id = (
                     SELECT latest.id FROM ai_workflow_analyses latest
                      WHERE latest.team_repository_id = a.team_repository_id
                        AND latest.status = 'succeeded'
                      ORDER BY latest.finished_at DESC NULLS LAST, latest.id DESC
                      LIMIT 1
                   )
               AND w.deleted_at IS NULL
               AND w.status <> 'ignored'
             ORDER BY w.id DESC, s.id
             LIMIT 1
            """, params, (rs, rowNum) -> new GatewayRequestAttribution(
                normalizedTag,
                rs.getInt("workflow_id"),
                rs.getInt("step_id"),
                requestSlo != null ? requestSlo : normalizeSlo(rs.getString("slo"))
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
               AND a.id = (
                     SELECT latest.id FROM ai_workflow_analyses latest
                      WHERE latest.team_repository_id = a.team_repository_id
                        AND latest.status = 'succeeded'
                      ORDER BY latest.finished_at DESC NULLS LAST, latest.id DESC
                      LIMIT 1
                   )
               AND w.deleted_at IS NULL
               AND w.status <> 'ignored'
             ORDER BY w.id DESC
             LIMIT 1
            """, params, (rs, rowNum) -> new GatewayRequestAttribution(
                normalizedTag,
                rs.getInt("workflow_id"),
                null,
                requestSlo
            ));
        if (!workflow.isEmpty()) {
            return workflow.getFirst();
        }
        return new GatewayRequestAttribution(normalizedTag, null, null, requestSlo);
    }

    private static String normalizeSlo(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        String slo = raw.trim().toLowerCase(Locale.ROOT);
        return VALID_SLOS.contains(slo) ? slo : null;
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
