package de.tum.cit.aet.logos.logoswebservice.identity.dto;

import java.util.List;

/**
 * Update a workflow's lifecycle, display tag, or soft-delete it.
 * Null fields are left unchanged; {@code deleted=true} soft-deletes.
 */
public record UpdateWorkflowRequestDTO(
    String status,
    String tag,
    Boolean deleted
) {}
