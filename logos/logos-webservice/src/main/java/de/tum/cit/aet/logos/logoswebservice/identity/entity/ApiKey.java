package de.tum.cit.aet.logos.logoswebservice.identity.entity;

import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
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

    @Column(nullable = false, unique = true)
    private String keyValue;

    @Column(nullable = false)
    private String name;

    @Enumerated(EnumType.STRING)
    @JdbcTypeCode(SqlTypes.NAMED_ENUM)
    @Column(columnDefinition = "api_key_type_enum", nullable = false)
    private ApiKeyType keyType;

    private Integer teamId;
    private Integer userId;
    private String environment;

    @Enumerated(EnumType.STRING)
    @JdbcTypeCode(SqlTypes.NAMED_ENUM)
    @Column(columnDefinition = "logging_enum")
    private LogLevel log;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(columnDefinition = "jsonb")
    private String settings;

    @Column(nullable = false)
    private Integer defaultPriority = 1;

    @Column(nullable = false)
    private Boolean isActive = true;

    @Column(nullable = false)
    private Boolean useCustomPermissions = false;

    public Integer getId() { return id; }
    public String getKeyValue() { return keyValue; }
    public String getName() { return name; }
    public ApiKeyType getKeyType() { return keyType; }
    public Integer getTeamId() { return teamId; }
    public Integer getUserId() { return userId; }
    public String getEnvironment() { return environment; }
    public LogLevel getLog() { return log; }
    public String getSettings() { return settings; }
    public Integer getDefaultPriority() { return defaultPriority; }
    public Boolean getIsActive() { return isActive; }
    public Boolean getUseCustomPermissions() { return useCustomPermissions; }

    public void setKeyValue(String keyValue) { this.keyValue = keyValue; }
    public void setName(String name) { this.name = name; }
    public void setKeyType(ApiKeyType keyType) { this.keyType = keyType; }
    public void setTeamId(Integer teamId) { this.teamId = teamId; }
    public void setUserId(Integer userId) { this.userId = userId; }
    public void setEnvironment(String environment) { this.environment = environment; }
    public void setLog(LogLevel log) { this.log = log; }
    public void setSettings(String settings) { this.settings = settings; }
    public void setDefaultPriority(Integer defaultPriority) { this.defaultPriority = defaultPriority; }
    public void setIsActive(Boolean isActive) { this.isActive = isActive; }
    public void setUseCustomPermissions(Boolean useCustomPermissions) { this.useCustomPermissions = useCustomPermissions; }
}
