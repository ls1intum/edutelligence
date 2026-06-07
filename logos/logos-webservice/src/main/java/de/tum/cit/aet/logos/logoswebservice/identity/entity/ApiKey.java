package de.tum.cit.aet.logos.logoswebservice.identity.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "api_keys")
public class ApiKey {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(name = "key_value", nullable = false, unique = true)
    private String keyValue;

    @Column(nullable = false)
    private String name;

    @Column(name = "key_type", nullable = false)
    private String keyType;

    @Column(name = "team_id")
    private Integer teamId;

    @Column(name = "user_id")
    private Integer userId;

    @Column(name = "environment")
    private String environment;

    @Column(name = "log")
    private String log;

    @Column(columnDefinition = "jsonb")
    private String settings;

    @Column(name = "default_priority", nullable = false)
    private Integer defaultPriority = 1;

    @Column(name = "is_active", nullable = false)
    private Boolean isActive = true;

    @Column(name = "use_custom_permissions", nullable = false)
    private Boolean useCustomPermissions = false;


    public Integer getId() { return id; }
    public String getKeyValue() { return keyValue; }
    public String getName() { return name; }
    public String getKeyType() { return keyType; }
    public Integer getTeamId() { return teamId; }
    public Integer getUserId() { return userId; }
    public String getEnvironment() { return environment; }
    public String getLog() { return log; }
    public String getSettings() { return settings; }
    public Integer getDefaultPriority() { return defaultPriority; }
    public Boolean getIsActive() { return isActive; }
    public Boolean getUseCustomPermissions() { return useCustomPermissions; }
    public void setKeyValue(String keyValue) { this.keyValue = keyValue; }
    public void setName(String name) { this.name = name; }
    public void setKeyType(String keyType) { this.keyType = keyType; }
    public void setTeamId(Integer teamId) { this.teamId = teamId; }
    public void setUserId(Integer userId) { this.userId = userId; }
    public void setEnvironment(String environment) { this.environment = environment; }
    public void setLog(String log) { this.log = log; }
    public void setSettings(String settings) { this.settings = settings; }
    public void setDefaultPriority(Integer defaultPriority) { this.defaultPriority = defaultPriority; }
    public void setIsActive(Boolean isActive) { this.isActive = isActive; }
    public void setUseCustomPermissions(Boolean useCustomPermissions) { this.useCustomPermissions = useCustomPermissions; }
}
