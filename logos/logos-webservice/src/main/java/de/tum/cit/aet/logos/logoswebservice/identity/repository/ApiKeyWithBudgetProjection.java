package de.tum.cit.aet.logos.logoswebservice.identity.repository;

public interface ApiKeyWithBudgetProjection {
    Integer getId();
    String getKeyValue();
    String getName();
    String getKeyType();
    Integer getUserId();
    String getEnvironment();
    String getLog();
    String getSettingsText();
    Integer getDefaultPriority();
    Boolean getIsActive();
    Boolean getUseCustomPermissions();
    Long getUsedMicroCents();
}
