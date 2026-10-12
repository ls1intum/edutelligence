package de.tum.cit.aet.logos.logoswebservice.identity.dto;

import java.util.List;

/** Confirm or override the SLO of a workflow step. */
public record UpdateWorkflowStepRequestDTO(
    String confirmedSlo,
    List<String> confirmedObjectivePriority,
    String tag,
    String name
) {}
