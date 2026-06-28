package de.tum.cit.aet.logos.logoswebservice.identity.dto;

import java.util.List;

public record TeamListResponseDTO(
    Integer id,
    String name,
    List<TeamOwnerResponseDTO> owners,
    Integer member_count,
    Integer model_count,
    Integer default_cloud_rpm_limit,
    Integer default_cloud_tpm_limit,
    Integer default_local_rpm_limit,
    Integer default_local_tpm_limit,
    Boolean is_caller_owner,
    boolean managed
) {}
