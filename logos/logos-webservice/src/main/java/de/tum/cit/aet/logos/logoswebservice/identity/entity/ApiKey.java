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

    private String environment;

    @Column(name = "log")
    private String log;

    @Column(columnDefinition = "jsonb")
    private String settings;

    @Column(name = "default_priority", nullable = false)
    private Integer defaultPriority = 1;

    @Column(name = "is_active", nullable = false)
    private Boolean isActive = true;

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
    public void setKeyValue(String keyValue) { this.keyValue = keyValue; }
    public void setIsActive(Boolean isActive) { this.isActive = isActive; }
    public void setUserId(Integer userId) { this.userId = userId; }
    public void setTeamId(Integer teamId) { this.teamId = teamId; }
    public void setName(String name) { this.name = name; }
    public void setKeyType(String keyType) { this.keyType = keyType; }
}