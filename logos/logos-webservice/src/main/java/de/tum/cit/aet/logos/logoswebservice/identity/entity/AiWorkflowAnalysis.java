package de.tum.cit.aet.logos.logoswebservice.identity.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "ai_workflow_analyses")
public class AiWorkflowAnalysis {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(nullable = false)
    private Integer teamId;

    @Column(nullable = false)
    private Integer teamRepositoryId;

    private String commitSha;

    @Column(nullable = false)
    private String status = "running";

    @Column(nullable = false)
    private String source = "heuristic";

    private Integer agentSessionId;
    private String error;

    @Column(nullable = false)
    private Instant startedAt;

    private Instant finishedAt;

    public Integer getId() { return id; }
    public Integer getTeamId() { return teamId; }
    public Integer getTeamRepositoryId() { return teamRepositoryId; }
    public String getCommitSha() { return commitSha; }
    public String getStatus() { return status; }
    public String getSource() { return source; }
    public Integer getAgentSessionId() { return agentSessionId; }
    public String getError() { return error; }
    public Instant getStartedAt() { return startedAt; }
    public Instant getFinishedAt() { return finishedAt; }

    public void setTeamId(Integer teamId) { this.teamId = teamId; }
    public void setTeamRepositoryId(Integer teamRepositoryId) { this.teamRepositoryId = teamRepositoryId; }
    public void setCommitSha(String commitSha) { this.commitSha = commitSha; }
    public void setStatus(String status) { this.status = status; }
    public void setSource(String source) { this.source = source; }
    public void setAgentSessionId(Integer agentSessionId) { this.agentSessionId = agentSessionId; }
    public void setError(String error) { this.error = error; }
    public void setStartedAt(Instant startedAt) { this.startedAt = startedAt; }
    public void setFinishedAt(Instant finishedAt) { this.finishedAt = finishedAt; }
}
