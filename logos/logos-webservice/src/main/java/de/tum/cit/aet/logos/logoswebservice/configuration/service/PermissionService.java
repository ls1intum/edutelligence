package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ApiKeyModelPermission;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ApiKeyProviderPermission;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.TeamModelPermission;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.TeamProviderPermission;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ApiKeyModelPermissionRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ApiKeyProviderPermissionRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.TeamModelPermissionRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.TeamProviderPermissionRepository;

@Service
public class PermissionService {

    private final ApiKeyModelPermissionRepository apiKeyModelRepo;
    private final ApiKeyProviderPermissionRepository apiKeyProviderRepo;
    private final TeamModelPermissionRepository teamModelRepo;
    private final TeamProviderPermissionRepository teamProviderRepo;

    public PermissionService(ApiKeyModelPermissionRepository apiKeyModelRepo,
                             ApiKeyProviderPermissionRepository apiKeyProviderRepo,
                             TeamModelPermissionRepository teamModelRepo,
                             TeamProviderPermissionRepository teamProviderRepo) {
        this.apiKeyModelRepo = apiKeyModelRepo;
        this.apiKeyProviderRepo = apiKeyProviderRepo;
        this.teamModelRepo = teamModelRepo;
        this.teamProviderRepo = teamProviderRepo;
    }

    public List<Integer> getApiKeyModelPermissions(int keyId) {
        return apiKeyModelRepo.findById_ApiKeyId(keyId).stream()
            .map(p -> p.getId().getModelId()).toList();
    }

    @Transactional
    public void setApiKeyModelPermissions(int keyId, List<Integer> modelIds) {
        apiKeyModelRepo.deleteById_ApiKeyId(keyId);
        apiKeyModelRepo.saveAll(modelIds.stream()
            .map(mid -> new ApiKeyModelPermission(keyId, mid)).toList());
    }

    public List<Integer> getApiKeyProviderPermissions(int keyId) {
        return apiKeyProviderRepo.findById_ApiKeyId(keyId).stream()
            .map(p -> p.getId().getProviderId()).toList();
    }

    @Transactional
    public void setApiKeyProviderPermissions(int keyId, List<Integer> providerIds) {
        apiKeyProviderRepo.deleteById_ApiKeyId(keyId);
        apiKeyProviderRepo.saveAll(providerIds.stream()
            .map(pid -> new ApiKeyProviderPermission(keyId, pid)).toList());
        apiKeyModelRepo.deleteCascadeForApiKey(keyId);
    }

    public List<Integer> getTeamModelPermissions(int teamId) {
        return teamModelRepo.findById_TeamId(teamId).stream()
            .map(p -> p.getId().getModelId()).toList();
    }

    @Transactional
    public void setTeamModelPermissions(int teamId, List<Integer> modelIds) {
        teamModelRepo.deleteById_TeamId(teamId);
        teamModelRepo.saveAll(modelIds.stream()
            .map(mid -> new TeamModelPermission(teamId, mid)).toList());
    }

    public List<Integer> getTeamProviderPermissions(int teamId) {
        return teamProviderRepo.findById_TeamId(teamId).stream()
            .map(p -> p.getId().getProviderId()).toList();
    }

    @Transactional
    public void setTeamProviderPermissions(int teamId, List<Integer> providerIds) {
        teamProviderRepo.deleteById_TeamId(teamId);
        teamProviderRepo.saveAll(providerIds.stream()
            .map(pid -> new TeamProviderPermission(teamId, pid)).toList());
        teamModelRepo.deleteCascadeForTeam(teamId);
    }
}
