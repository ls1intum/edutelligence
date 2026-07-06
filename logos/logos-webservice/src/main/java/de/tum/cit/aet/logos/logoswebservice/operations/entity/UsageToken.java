package de.tum.cit.aet.logos.logoswebservice.operations.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "usage_tokens")
public class UsageToken {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    private Integer typeId;
    private Integer logEntryId;
    private Integer tokenCount;

    public Integer getId() { return id; }
    public Integer getTypeId() { return typeId; }
    public Integer getLogEntryId() { return logEntryId; }
    public Integer getTokenCount() { return tokenCount; }
    public void setTypeId(Integer typeId) { this.typeId = typeId; }
    public void setLogEntryId(Integer logEntryId) { this.logEntryId = logEntryId; }
    public void setTokenCount(Integer tokenCount) { this.tokenCount = tokenCount; }
}
