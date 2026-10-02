package de.tum.cit.aet.logos.logoswebservice.identity.dto;

import java.util.List;

public record UpdateTeamRepoLinkRequestDTO(
    String repoUrl,
    String branch,
    List<String> paths
) {}
