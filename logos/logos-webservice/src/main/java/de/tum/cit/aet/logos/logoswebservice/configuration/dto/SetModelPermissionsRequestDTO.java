package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

import java.util.List;

public record SetModelPermissionsRequestDTO(
    List<Integer> modelIds
) {}
