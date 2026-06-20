package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.sql.Timestamp;

public interface MyKeyProjection {
    Integer getId();
    String getKeyValue();
    String getName();
    String getKeyType();
    String getEnvironment();
    String getLog();
    Boolean getUseCustomPermissions();
    String getSettingsText();
    Integer getTeamId();
    String getTeamName();
    Long getTeamMonthlyBudgetMicroCents();
    Long getUsedMicroCents();
    Long getTeamBudgetUsedMicroCents();
    Timestamp getLastUsedAt();
}
