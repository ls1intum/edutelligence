package de.tum.cit.aet.logos.logoswebservice.identity.dto;

import java.util.List;

public record TeamListResponse(
    Integer id,
    String name,
    List<TeamOwnerResponse> owners,
    Integer member_count,
    Integer model_count,
    Integer default_cloud_rpm_limit,
    Integer default_cloud_tpm_limit,
    Integer default_local_rpm_limit,
    Integer default_local_tpm_limit,
    Boolean is_caller_owner
) {}
