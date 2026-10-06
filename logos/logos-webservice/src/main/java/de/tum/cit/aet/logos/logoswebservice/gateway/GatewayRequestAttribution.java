package de.tum.cit.aet.logos.logoswebservice.gateway;

/**
 * Optional workflow / SLA attribution parsed from inbound inference headers.
 *
 * <p>Applications may send {@code X-Logos-Workflow-Tag} and/or {@code X-Logos-SLA}
 * so Logos can attribute traffic to a workflow step and (on the orchestrator
 * path) elevate queue priority. Direct-cloud gateway rows store the same
 * columns for historic workflow benchmarks.
 */
public record GatewayRequestAttribution(
    String workflowTag,
    Integer workflowId,
    Integer workflowStepId,
    String requestSla
) {
    public static final GatewayRequestAttribution EMPTY =
        new GatewayRequestAttribution(null, null, null, null);
}
