package de.tum.cit.aet.logos.logoswebservice.identity.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.Map;
import java.util.Optional;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import de.tum.cit.aet.logos.logoswebservice.audit.AuditLogService;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Provider;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ProviderType;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpsertTeamProviderBudgetRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamProviderBudget;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamProviderBudgetId;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamProviderBudgetRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;

/** A sponsored budget changes how much a team can spend, so every change must say who made it. */
class TeamProviderBudgetServiceAuditTest {

    private TeamProviderBudgetRepository budgets;
    private AuditLogService audit;
    private TeamProviderBudgetService service;

    @BeforeEach
    void setUp() {
        TeamRepository teams = mock(TeamRepository.class);
        ProviderRepository providers = mock(ProviderRepository.class);
        budgets = mock(TeamProviderBudgetRepository.class);
        audit = mock(AuditLogService.class);
        when(teams.existsById(3)).thenReturn(true);
        Provider provider = mock(Provider.class);
        when(provider.getProviderType()).thenReturn(ProviderType.cloud);
        when(providers.findById(4)).thenReturn(Optional.of(provider));
        service = new TeamProviderBudgetService(teams, mock(TeamMemberRepository.class), budgets, providers, audit);
    }

    @Test
    @SuppressWarnings("unchecked")
    void makingAProviderUnlimitedIsAuditedWithItsPreviousCap() {
        when(budgets.findById(new TeamProviderBudgetId(3, 4)))
            .thenReturn(Optional.of(new TeamProviderBudget(3, 4, 500L)));

        service.upsert(3, new UpsertTeamProviderBudgetRequestDTO(4, null));

        ArgumentCaptor<Map<String, Object>> before = ArgumentCaptor.forClass(Map.class);
        ArgumentCaptor<Map<String, Object>> after = ArgumentCaptor.forClass(Map.class);
        verify(audit).record(eq("team.provider_budget_set"), eq("team_provider_budget"), eq("3/4"), eq(3),
            before.capture(), after.capture());
        assertThat(before.getValue()).containsEntry("monthly_budget_micro_cents", 500L);
        assertThat(after.getValue()).containsEntry("sponsored", true)
            .containsEntry("monthly_budget_micro_cents", null);
    }

    @Test
    void removingAnOverrideIsAudited() {
        when(budgets.findById(new TeamProviderBudgetId(3, 4)))
            .thenReturn(Optional.of(new TeamProviderBudget(3, 4, null)));

        assertThat(service.delete(3, 4)).isTrue();

        verify(audit).record(eq("team.provider_budget_removed"), eq("team_provider_budget"), eq("3/4"), eq(3),
            any(), any());
    }

    @Test
    void removingNothingIsNotAudited() {
        when(budgets.findById(any(TeamProviderBudgetId.class))).thenReturn(Optional.empty());

        assertThat(service.delete(3, 4)).isFalse();

        verify(audit, never()).record(any(), any(), any(), any(), any(), any());
    }
}
