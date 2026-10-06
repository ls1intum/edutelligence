package de.tum.cit.aet.logos.logoswebservice.identity.dto;

import java.util.List;

/** Confirm or override the SLA of a workflow step. */
public record UpdateWorkflowStepRequestDTO(
    String confirmedSla,
    List<String> confirmedObjectivePriority,
    String tag,
    String name
) {}
