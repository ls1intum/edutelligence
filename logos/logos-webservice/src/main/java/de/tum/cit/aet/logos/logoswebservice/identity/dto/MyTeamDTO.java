package de.tum.cit.aet.logos.logoswebservice.identity.dto;

import java.util.List;

public record MyTeamDTO(
    Integer id,
    String name,
    Boolean is_caller_owner,
    Long team_monthly_budget_micro_cents,
    Long budget_used_micro_cents,
    Integer member_count,
    List<MyTeamOwnerDTO> owners
) {}
