package de.tum.cit.aet.logos.logoswebservice.identity.dto;

/** Compare a workflow's historic tagged traffic against a candidate model. */
public record WorkflowBenchmarkRequestDTO(
    String candidateModel,
    Integer sampleSize
) {}
