package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.util.List;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PermissionService {

    private final JdbcTemplate jdbcTemplate;

    public PermissionService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public List<Integer> getApiKeyModelPermissions(int keyId) {
        return jdbcTemplate.queryForList(
            "SELECT model_id FROM api_key_model_permissions WHERE api_key_id = ?",
            Integer.class, keyId);
    }

    @Transactional
    public void setApiKeyModelPermissions(int keyId, List<Integer> modelIds) {
        jdbcTemplate.update("DELETE FROM api_key_model_permissions WHERE api_key_id = ?", keyId);
        for (int mid : modelIds) {
            jdbcTemplate.update(
                "INSERT INTO api_key_model_permissions (api_key_id, model_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                keyId, mid);
        }
    }

    public List<Integer> getApiKeyProviderPermissions(int keyId) {
        return jdbcTemplate.queryForList(
            "SELECT provider_id FROM api_key_provider_permissions WHERE api_key_id = ?",
            Integer.class, keyId);
    }

    @Transactional
    public void setApiKeyProviderPermissions(int keyId, List<Integer> providerIds) {
        jdbcTemplate.update("DELETE FROM api_key_provider_permissions WHERE api_key_id = ?", keyId);
        for (int pid : providerIds) {
            jdbcTemplate.update(
                "INSERT INTO api_key_provider_permissions (api_key_id, provider_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                keyId, pid);
        }
        jdbcTemplate.update("""
            DELETE FROM api_key_model_permissions
            WHERE api_key_id = ?
              AND model_id NOT IN (
                  SELECT DISTINCT mp.model_id FROM model_provider mp
                  JOIN api_key_provider_permissions akpp ON mp.provider_id = akpp.provider_id
                  WHERE akpp.api_key_id = ?
              )
            """, keyId, keyId);
    }

    public List<Integer> getTeamModelPermissions(int teamId) {
        return jdbcTemplate.queryForList(
            "SELECT model_id FROM team_model_permissions WHERE team_id = ?",
            Integer.class, teamId);
    }

    @Transactional
    public void setTeamModelPermissions(int teamId, List<Integer> modelIds) {
        jdbcTemplate.update("DELETE FROM team_model_permissions WHERE team_id = ?", teamId);
        for (int mid : modelIds) {
            jdbcTemplate.update(
                "INSERT INTO team_model_permissions (team_id, model_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                teamId, mid);
        }
    }

    public List<Integer> getTeamProviderPermissions(int teamId) {
        return jdbcTemplate.queryForList(
            "SELECT provider_id FROM team_provider_permissions WHERE team_id = ?",
            Integer.class, teamId);
    }

    @Transactional
    public void setTeamProviderPermissions(int teamId, List<Integer> providerIds) {
        jdbcTemplate.update("DELETE FROM team_provider_permissions WHERE team_id = ?", teamId);
        for (int pid : providerIds) {
            jdbcTemplate.update(
                "INSERT INTO team_provider_permissions (team_id, provider_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                teamId, pid);
        }
        jdbcTemplate.update("""
            DELETE FROM team_model_permissions
            WHERE team_id = ?
              AND model_id NOT IN (
                  SELECT DISTINCT mp.model_id FROM model_provider mp
                  JOIN team_provider_permissions tpp ON mp.provider_id = tpp.provider_id
                  WHERE tpp.team_id = ?
              )
            """, teamId, teamId);
    }
}
