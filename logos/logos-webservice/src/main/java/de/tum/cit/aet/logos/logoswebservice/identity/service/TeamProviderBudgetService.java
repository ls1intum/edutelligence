package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Provider;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ProviderType;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpsertTeamProviderBudgetRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamProviderBudget;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamProviderBudgetId;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamProviderBudgetRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;

@Service
public class TeamProviderBudgetService {

    private final TeamRepository teamRepository;
    private final TeamMemberRepository memberRepository;
    private final TeamProviderBudgetRepository budgetRepository;
    private final ProviderRepository providerRepository;

    public TeamProviderBudgetService(
            TeamRepository teamRepository,
            TeamMemberRepository memberRepository,
            TeamProviderBudgetRepository budgetRepository,
            ProviderRepository providerRepository) {
        this.teamRepository = teamRepository;
        this.memberRepository = memberRepository;
        this.budgetRepository = budgetRepository;
        this.providerRepository = providerRepository;
    }

    public boolean teamExists(Integer teamId) {
        return teamRepository.existsById(teamId);
    }

    public boolean isTeamOwner(Integer teamId, Integer userId) {
        return memberRepository.isOwner(teamId, userId);
    }

    public List<Map<String, Object>> listForTeam(Integer teamId) {
        return budgetRepository.listForTeam(teamId).stream()
            .map(row -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("provider_id", row.getProviderId());
                m.put("provider_name", row.getProviderName());
                m.put("provider_type", row.getProviderType());
                m.put("monthly_budget_micro_cents", row.getMonthlyBudgetMicroCents());
                return m;
            })
            .toList();
    }

    @Transactional
    public Map<String, Object> upsert(Integer teamId, UpsertTeamProviderBudgetRequestDTO body) {
        if (!teamRepository.existsById(teamId)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Team not found");
        }
        if (body == null || body.provider_id() == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "provider_id is required");
        }
        if (body.monthly_budget_micro_cents() != null && body.monthly_budget_micro_cents() < 0) {
            throw new ResponseStatusException(
                HttpStatus.BAD_REQUEST, "monthly_budget_micro_cents must be null or >= 0");
        }
        Provider provider = providerRepository.findById(body.provider_id())
            .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Provider not found"));
        if (provider.getProviderType() != ProviderType.cloud) {
            throw new ResponseStatusException(
                HttpStatus.BAD_REQUEST, "Only cloud providers can have a sponsored budget");
        }

        TeamProviderBudgetId id = new TeamProviderBudgetId(teamId, body.provider_id());
        TeamProviderBudget row = budgetRepository.findById(id)
            .orElseGet(() -> new TeamProviderBudget(teamId, body.provider_id(), null));
        row.setMonthlyBudgetMicroCents(body.monthly_budget_micro_cents());
        budgetRepository.save(row);

        Map<String, Object> m = new LinkedHashMap<>();
        m.put("provider_id", provider.getId());
        m.put("provider_name", provider.getName());
        m.put("provider_type", provider.getProviderType() == null ? null : provider.getProviderType().name());
        m.put("monthly_budget_micro_cents", row.getMonthlyBudgetMicroCents());
        return m;
    }

    @Transactional
    public boolean delete(Integer teamId, Integer providerId) {
        TeamProviderBudgetId id = new TeamProviderBudgetId(teamId, providerId);
        if (!budgetRepository.existsById(id)) {
            return false;
        }
        budgetRepository.deleteById(id);
        return true;
    }

    public Optional<TeamProviderBudget> find(Integer teamId, Integer providerId) {
        return budgetRepository.findById(new TeamProviderBudgetId(teamId, providerId));
    }
}
