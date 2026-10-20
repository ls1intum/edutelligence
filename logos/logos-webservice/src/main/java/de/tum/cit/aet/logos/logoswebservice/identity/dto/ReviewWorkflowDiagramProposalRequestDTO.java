package de.tum.cit.aet.logos.logoswebservice.identity.dto;

/**
 * Accept the agent's proposed diagram, or dismiss it and keep the owner's.
 * {@code action} is {@code accept} or {@code dismiss}.
 */
public record ReviewWorkflowDiagramProposalRequestDTO(String action) {}
