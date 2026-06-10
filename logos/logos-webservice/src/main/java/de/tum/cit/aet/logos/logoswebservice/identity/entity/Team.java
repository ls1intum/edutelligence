package de.tum.cit.aet.logos.logoswebservice.identity.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "teams")
public class Team {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(nullable = false)
    private String name;

    private Integer defaultCloudRpmLimit = 5;
    private Integer defaultCloudTpmLimit = 10000;
    private Integer defaultLocalRpmLimit = 5;
    private Integer defaultLocalTpmLimit = 10000;
    private Long defaultMonthlyBudgetMicroCents = 100000000L;
    private Long teamMonthlyBudgetMicroCents = 500000000L;

    public Integer getId() { return id; }
    public String getName() { return name; }
    public Integer getDefaultCloudRpmLimit() { return defaultCloudRpmLimit; }
    public Integer getDefaultCloudTpmLimit() { return defaultCloudTpmLimit; }
    public Integer getDefaultLocalRpmLimit() { return defaultLocalRpmLimit; }
    public Integer getDefaultLocalTpmLimit() { return defaultLocalTpmLimit; }
    public Long getDefaultMonthlyBudgetMicroCents() { return defaultMonthlyBudgetMicroCents; }
    public Long getTeamMonthlyBudgetMicroCents() { return teamMonthlyBudgetMicroCents; }
    public void setName(String name) { this.name = name; }
    public void setDefaultCloudRpmLimit(Integer v) { this.defaultCloudRpmLimit = v; }
    public void setDefaultCloudTpmLimit(Integer v) { this.defaultCloudTpmLimit = v; }
    public void setDefaultLocalRpmLimit(Integer v) { this.defaultLocalRpmLimit = v; }
    public void setDefaultLocalTpmLimit(Integer v) { this.defaultLocalTpmLimit = v; }
    public void setDefaultMonthlyBudgetMicroCents(Long v) { this.defaultMonthlyBudgetMicroCents = v; }
    public void setTeamMonthlyBudgetMicroCents(Long v) { this.teamMonthlyBudgetMicroCents = v; }
}
