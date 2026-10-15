package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

/** Taking one's vote back for a requested model, by the model's name. */
public record RemoveModelRequestDTO(
    String name
) {}
