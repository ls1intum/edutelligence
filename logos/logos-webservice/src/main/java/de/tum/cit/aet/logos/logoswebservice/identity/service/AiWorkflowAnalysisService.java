package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;

import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;

import de.tum.cit.aet.logos.logoswebservice.identity.ObjectivePriority;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.ReviewRecommendationRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.StoreDeployKeyRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateApiKeyRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.AiLlmCallRecommendation;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.AiWorkflow;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.AiWorkflowAnalysis;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamRepoLink;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamRepositoryCredential;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.AiLlmCallRecommendationRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.AiWorkflowAnalysisRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.AiWorkflowRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepoLinkRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepositoryCredentialRepository;

@Service
public class AiWorkflowAnalysisService {

    private static final Set<String> VALID_SLAS = Set.of("ux-critical", "ux-high-prio", "ux-background");
    private static final Set<String> REVIEW_ACTIONS = Set.of("accept", "override", "reject");

    /**
     * Same contract as logos-agent {@code analysis_triggers.ANALYSIS_TASK}.
     */
    static final String ANALYSIS_TASK_TEMPLATE = """
        Analyse this linked application repository for AI / LLM call sites and produce
        workflow diagrams plus SLA recommendations.

        Write structured results ONLY to `/artifacts/analysis.json` (UTF-8 JSON).
        Do not push commits, open pull requests, or modify the remote.

        Schema for `/artifacts/analysis.json`:
        {
          "commit_sha": "<git HEAD sha of the checkout you analysed>",
          "workflows": [
            {
              "name": "<short workflow group name>",
              "trigger_summary": "<what starts this flow>",
              "diagram_mermaid": "flowchart TD\\n  A-->B",
              "sort_order": 0
            }
          ],
          "recommendations": [
            {
              "workflow": "<matching workflows[].name>",
              "file_path": "path/from/repo/root.py",
              "start_line": 1,
              "end_line": 20,
              "code_url": "optional permalink to the call site, or null",
              "detected_model": "optional model name or null",
              "recommended_sla": "ux-critical" | "ux-high-prio" | "ux-background",
              "objective_priority": ["latency" | "quality" | "price", "..."],
              "confidence": 0.0,
              "justification": "why this SLA and objective order",
              "traffic_flags": {"night_heavy": false}
            }
          ]
        }

        `objective_priority` is a full ranking of latency, quality, and price (most
        important first). It complements SLA: SLA is urgency/interactivity; the ranking
        says what to optimize for when choosing a model. If omitted, defaults are:
        ux-critical → [latency, quality, price]; ux-high-prio → [quality, latency, price];
        ux-background → [price, quality, latency].

        Repository: %s
        Clone URL: %s
        Focus paths (empty means whole tree): %s
        """;

    private final TeamMemberRepository teamMemberRepository;
    private final TeamRepository teamRepository;
    private final TeamRepoLinkRepository repoLinkRepository;
    private final TeamRepositoryCredentialRepository credentialRepository;
    private final AiWorkflowAnalysisRepository analysisRepository;
    private final AiWorkflowRepository workflowRepository;
    private final AiLlmCallRecommendationRepository recommendationRepository;
    private final ApiKeyRepository apiKeyRepository;
    private final ApiKeyAdminService apiKeyAdminService;
    private final RepoWorkflowScanner scanner;
    private final RepoCredentialCrypto crypto;
    private final JdbcTemplate jdbc;
    private final TransactionTemplate requiresNewTx;

    public AiWorkflowAnalysisService(TeamMemberRepository teamMemberRepository,
                                     TeamRepository teamRepository,
                                     TeamRepoLinkRepository repoLinkRepository,
                                     TeamRepositoryCredentialRepository credentialRepository,
                                     AiWorkflowAnalysisRepository analysisRepository,
                                     AiWorkflowRepository workflowRepository,
                                     AiLlmCallRecommendationRepository recommendationRepository,
                                     ApiKeyRepository apiKeyRepository,
                                     ApiKeyAdminService apiKeyAdminService,
                                     RepoWorkflowScanner scanner,
                                     RepoCredentialCrypto crypto,
                                     JdbcTemplate jdbc,
                                     PlatformTransactionManager txManager) {
        this.teamMemberRepository = teamMemberRepository;
        this.teamRepository = teamRepository;
        this.repoLinkRepository = repoLinkRepository;
        this.credentialRepository = credentialRepository;
        this.analysisRepository = analysisRepository;
        this.workflowRepository = workflowRepository;
        this.recommendationRepository = recommendationRepository;
        this.apiKeyRepository = apiKeyRepository;
        this.apiKeyAdminService = apiKeyAdminService;
        this.scanner = scanner;
        this.crypto = crypto;
        this.jdbc = jdbc;
        this.requiresNewTx = new TransactionTemplate(txManager);
        this.requiresNewTx.setPropagationBehavior(
            TransactionTemplate.PROPAGATION_REQUIRES_NEW);
    }

    public boolean isTeamOwner(int teamId, int userId) {
        return teamMemberRepository.isOwner(teamId, userId);
    }

    public boolean teamExists(int teamId) {
        return teamRepository.existsById(teamId);
    }

    public Map<String, Object> listTeamWorkflows(int teamId) {
        if (!teamExists(teamId)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Team not found");
        }
        List<TeamRepoLink> links = repoLinkRepository.findByTeamIdOrderByRepoSlugAsc(teamId);
        List<Map<String, Object>> repositories = new ArrayList<>();
        for (TeamRepoLink link : links) {
            Map<String, Object> repo = new LinkedHashMap<>();
            repo.put("id", link.getId());
            repo.put("repo_slug", link.getRepoSlug());
            repo.put("repo_url", link.getRepoUrl());
            repo.put("branch", link.getBranch());

            Optional<AiWorkflowAnalysis> latest = analysisRepository
                .findFirstByTeamRepositoryIdAndStatusOrderByFinishedAtDesc(link.getId(), "succeeded");
            if (latest.isPresent()) {
                AiWorkflowAnalysis analysis = latest.get();
                repo.put("latest_analysis", analysisToMap(analysis));
                List<AiWorkflow> workflows = workflowRepository
                    .findByAnalysisIdOrderBySortOrderAsc(analysis.getId());
                repo.put("workflows", workflows.stream().map(this::workflowToMap).toList());
                List<AiLlmCallRecommendation> recs = recommendationRepository
                    .findByAnalysisIdOrderByIdAsc(analysis.getId());
                repo.put("recommendations", recs.stream().map(this::recommendationToMap).toList());
            }
            else {
                repo.put("latest_analysis", null);
                repo.put("workflows", List.of());
                repo.put("recommendations", List.of());
            }
            repositories.add(repo);
        }

        List<AiLlmCallRecommendation> pending = recommendationRepository
            .findByTeamIdAndReviewStatusOrderByIdAsc(teamId, "pending");

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("team_id", teamId);
        result.put("repositories", repositories);
        result.put("pending_recommendations", pending.stream().map(this::recommendationToMap).toList());
        return result;
    }

    /**
     * Heuristic scan. Failure records commit in a separate transaction so a
     * rolled-back scan does not erase the failed analysis row.
     */
    public Map<String, Object> runHeuristicAnalysis(int teamId, int linkId) {
        TeamRepoLink link = requireLink(teamId, linkId);
        AiWorkflowAnalysis analysis = requiresNewTx.execute(status -> {
            AiWorkflowAnalysis row = new AiWorkflowAnalysis();
            row.setTeamId(teamId);
            row.setTeamRepositoryId(link.getId());
            row.setStatus("running");
            row.setSource("heuristic");
            row.setStartedAt(Instant.now());
            return analysisRepository.saveAndFlush(row);
        });
        if (analysis == null) {
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR,
                "Failed to create analysis row");
        }
        final int analysisId = analysis.getId();

        try {
            String deployKeyPem = decryptActiveDeployKey(link.getId());
            RepoWorkflowScanner.ScanResult scan = scanner.scanGithub(
                link.getRepoSlug(), link.getBranch(), link.getPaths(), deployKeyPem);
            return requiresNewTx.execute(status -> persistHeuristicSuccess(analysisId, teamId, link, scan));
        }
        catch (ResponseStatusException e) {
            markAnalysisFailed(analysisId, e.getReason());
            throw e;
        }
        catch (RuntimeException e) {
            String msg = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
            markAnalysisFailed(analysisId, msg);
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR,
                "Heuristic analysis failed: " + msg, e);
        }
    }

    private Map<String, Object> persistHeuristicSuccess(int analysisId, int teamId, TeamRepoLink link,
                                                        RepoWorkflowScanner.ScanResult scan) {
        AiWorkflowAnalysis analysis = analysisRepository.findById(analysisId)
            .orElseThrow(() -> new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR,
                "Analysis row missing"));
        analysis.setCommitSha(scan.commitSha());

        Map<String, Integer> workflowIdsByName = new LinkedHashMap<>();
        for (RepoWorkflowScanner.WorkflowGroup group : scan.workflows()) {
            AiWorkflow workflow = new AiWorkflow();
            workflow.setAnalysisId(analysis.getId());
            workflow.setName(group.name());
            workflow.setTriggerSummary(group.triggerSummary());
            workflow.setDiagramMermaid(group.diagramMermaid());
            workflow.setSortOrder(group.sortOrder());
            workflow = workflowRepository.save(workflow);
            workflowIdsByName.put(group.name(), workflow.getId());
        }

        Map<String, Boolean> nightHeavyByModel = nightHeavyModels(teamId);
        List<AiLlmCallRecommendation> savedRecs = new ArrayList<>();
        for (RepoWorkflowScanner.DetectedCall call : scan.calls()) {
            AiLlmCallRecommendation rec = new AiLlmCallRecommendation();
            rec.setAnalysisId(analysis.getId());
            String group = workflowGroupName(call.filePath());
            rec.setWorkflowId(workflowIdsByName.get(group));
            rec.setTeamId(teamId);
            rec.setFilePath(call.filePath());
            rec.setStartLine(call.startLine());
            rec.setEndLine(call.endLine());
            rec.setCodeUrl(buildCodeUrl(link, scan.commitSha(), call.filePath(), call.startLine()));
            rec.setDetectedModel(call.detectedModel());
            rec.setRecommendedSla(call.recommendedSla());
            rec.setObjectivePriority(ObjectivePriority.asJsonList(call.objectivePriority()));
            rec.setConfidence(call.confidence());
            rec.setJustification(call.justification());
            rec.setReviewStatus("pending");

            Map<String, Object> flags = new LinkedHashMap<>();
            boolean nightHeavy = false;
            if ("ux-critical".equals(call.recommendedSla()) && call.detectedModel() != null) {
                nightHeavy = Boolean.TRUE.equals(nightHeavyByModel.get(
                    call.detectedModel().toLowerCase(Locale.ROOT)));
            }
            flags.put("night_heavy", nightHeavy);
            rec.setTrafficFlags(flags);
            savedRecs.add(recommendationRepository.save(rec));
        }

        analysis.setStatus("succeeded");
        analysis.setFinishedAt(Instant.now());
        analysisRepository.save(analysis);

        Map<String, Object> result = analysisToMap(analysis);
        result.put("workflows", workflowRepository.findByAnalysisIdOrderBySortOrderAsc(analysis.getId())
            .stream().map(this::workflowToMap).toList());
        result.put("recommendations", savedRecs.stream().map(this::recommendationToMap).toList());
        return result;
    }

    private void markAnalysisFailed(int analysisId, String error) {
        requiresNewTx.executeWithoutResult(status -> {
            analysisRepository.findById(analysisId).ifPresent(row -> {
                row.setStatus("failed");
                row.setError(error);
                row.setFinishedAt(Instant.now());
                analysisRepository.save(row);
            });
        });
    }

    private String decryptActiveDeployKey(int linkId) {
        Optional<TeamRepositoryCredential> cred = credentialRepository.findById(linkId);
        if (cred.isEmpty() || cred.get().getRevokedAt() != null) {
            return null;
        }
        String encrypted = cred.get().getEncryptedPrivateKey();
        if (encrypted == null || encrypted.isBlank()) {
            return null;
        }
        return crypto.decrypt(encrypted);
    }

    @Transactional
    public Map<String, Object> reviewRecommendation(int teamId, int recId,
                                                    ReviewRecommendationRequestDTO body,
                                                    int reviewerUserId) {
        if (body == null || body.action() == null || body.action().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "action is required");
        }
        String action = body.action().trim().toLowerCase(Locale.ROOT);
        if (!REVIEW_ACTIONS.contains(action)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                "action must be accept, override, or reject");
        }

        AiLlmCallRecommendation rec = recommendationRepository.findByIdAndTeamId(recId, teamId)
            .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND,
                "Recommendation not found"));

        Instant now = Instant.now();
        rec.setReviewedBy(reviewerUserId);
        rec.setReviewedAt(now);

        if ("reject".equals(action)) {
            rec.setReviewStatus("rejected");
            rec.setConfirmedSla(null);
            rec.setConfirmedObjectivePriority(null);
            recommendationRepository.save(rec);
            return recommendationToMap(rec);
        }

        String confirmedSla;
        List<Object> confirmedPriority;
        if ("accept".equals(action)) {
            confirmedSla = rec.getRecommendedSla();
            if (body.confirmedSla() != null && !body.confirmedSla().isBlank()) {
                confirmedSla = body.confirmedSla().trim();
            }
            confirmedPriority = ObjectivePriority.asJsonList(
                body.confirmedObjectivePriority() != null
                    ? body.confirmedObjectivePriority()
                    : ObjectivePriority.asStringList(rec.getObjectivePriority()));
            rec.setReviewStatus("accepted");
        }
        else {
            if (body.confirmedSla() == null || body.confirmedSla().isBlank()) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "confirmed_sla is required for override");
            }
            confirmedSla = body.confirmedSla().trim();
            confirmedPriority = ObjectivePriority.asJsonList(
                body.confirmedObjectivePriority() != null
                    ? body.confirmedObjectivePriority()
                    : ObjectivePriority.asStringList(rec.getObjectivePriority()));
            rec.setReviewStatus("overridden");
        }
        if (!VALID_SLAS.contains(confirmedSla)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                "confirmed_sla must be ux-critical, ux-high-prio, or ux-background");
        }
        rec.setConfirmedSla(confirmedSla);
        rec.setConfirmedObjectivePriority(confirmedPriority);

        Integer apiKeyId = body.apiKeyId() != null ? body.apiKeyId() : rec.getApiKeyId();
        if (apiKeyId != null) {
            var key = apiKeyRepository.findById(apiKeyId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "API key not found: " + apiKeyId));
            if (key.getTeamId() == null || !key.getTeamId().equals(teamId)) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "API key does not belong to this team");
            }
            rec.setApiKeyId(apiKeyId);
            int priority = slaToPriority(confirmedSla);
            apiKeyAdminService.updateKey(apiKeyId, new UpdateApiKeyRequestDTO(
                null, priority, null, null, null, null, null, null, null));
        }

        recommendationRepository.save(rec);
        return recommendationToMap(rec);
    }

    @Transactional
    public Map<String, Object> storeDeployKey(int teamId, int linkId, StoreDeployKeyRequestDTO body) {
        TeamRepoLink link = requireLink(teamId, linkId);
        if (body == null || body.privateKeyPem() == null || body.privateKeyPem().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "private_key_pem is required");
        }
        String pem = body.privateKeyPem().trim();
        if (!pem.contains("PRIVATE KEY")) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                "private_key_pem does not look like a PEM private key");
        }
        String fingerprint = body.publicKeyFingerprint();
        if (fingerprint == null || fingerprint.isBlank()) {
            fingerprint = RepoCredentialCrypto.fingerprint(pem);
        }

        Instant now = Instant.now();
        TeamRepositoryCredential cred = credentialRepository.findById(link.getId())
            .orElseGet(TeamRepositoryCredential::new);
        cred.setTeamRepositoryId(link.getId());
        cred.setAccessType("deploy_key");
        cred.setEncryptedPrivateKey(crypto.encrypt(pem));
        cred.setPublicKeyFingerprint(fingerprint.trim());
        cred.setGithubAppInstallationId(null);
        if (cred.getCreatedAt() == null) {
            cred.setCreatedAt(now);
        }
        cred.setRevokedAt(null);
        credentialRepository.save(cred);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("team_repository_id", link.getId());
        result.put("access_type", "deploy_key");
        result.put("public_key_fingerprint", cred.getPublicKeyFingerprint());
        result.put("created_at", cred.getCreatedAt().toString());
        result.put("has_credentials", true);
        return result;
    }

    @Transactional
    public boolean revokeCredentials(int teamId, int linkId) {
        TeamRepoLink link = requireLink(teamId, linkId);
        Optional<TeamRepositoryCredential> existing = credentialRepository.findById(link.getId());
        if (existing.isEmpty() || existing.get().getRevokedAt() != null) {
            return false;
        }
        TeamRepositoryCredential cred = existing.get();
        cred.setEncryptedPrivateKey(null);
        cred.setRevokedAt(Instant.now());
        credentialRepository.save(cred);
        return true;
    }

    /**
     * Queues a read-only agent analysis session ({@code no_push=true},
     * {@code trigger_kind=analysis}) and a matching {@code ai_workflow_analyses}
     * row in {@code queued} status.
     */
    @Transactional
    public Map<String, Object> queueAgentAnalysis(int teamId, int linkId) {
        TeamRepoLink link = requireLink(teamId, linkId);
        int workspaceId = ensureAnalysisWorkspace(teamId, link);

        String pathsLabel = formatPaths(link.getPaths());
        String task = ANALYSIS_TASK_TEMPLATE.formatted(
            link.getRepoSlug(),
            link.getRepoUrl(),
            pathsLabel);

        Integer sessionId = jdbc.queryForObject("""
            INSERT INTO agent_sessions (
                workspace_id, task, model, status, created_by,
                open_pull_request, deploy_to_dev, screenshot_paths,
                no_push, trigger_kind, trigger_ref,
                repo_url, repo_slug, team_repository_id, priority, priority_reason
            ) VALUES (
                ?, ?, NULL, 'queued', ?,
                FALSE, FALSE, '[]'::jsonb,
                TRUE, 'analysis', ?,
                ?, ?, ?, 10, 'workflow analysis — spare capacity'
            ) RETURNING id
            """, Integer.class,
            workspaceId,
            task,
            "team-" + teamId,
            "team-repository:" + link.getId(),
            link.getRepoUrl(),
            link.getRepoSlug(),
            link.getId());

        Instant now = Instant.now();
        AiWorkflowAnalysis analysis = new AiWorkflowAnalysis();
        analysis.setTeamId(teamId);
        analysis.setTeamRepositoryId(link.getId());
        analysis.setStatus("queued");
        analysis.setSource("agent");
        analysis.setAgentSessionId(sessionId);
        analysis.setStartedAt(now);
        analysis = analysisRepository.save(analysis);

        Map<String, Object> result = analysisToMap(analysis);
        result.put("agent_session_id", sessionId);
        result.put("message", "Agent analysis queued");
        return result;
    }

    private static String formatPaths(List<String> paths) {
        if (paths == null || paths.isEmpty()) {
            return "(entire repository)";
        }
        return paths.stream().filter(p -> p != null && !p.isBlank()).collect(Collectors.joining(", "));
    }

    private int ensureAnalysisWorkspace(int teamId, TeamRepoLink link) {
        String name = "analysis-team-" + teamId + "-repo-" + link.getId();
        String branch = link.getBranch() != null ? link.getBranch() : "main";
        String volume = "logos-analysis-t" + teamId + "-r" + link.getId();
        Integer id = jdbc.queryForObject("""
            INSERT INTO agent_workspaces (name, base_branch, volume_name, created_by, ephemeral)
            VALUES (?, ?, ?, ?, TRUE)
            ON CONFLICT (name) DO UPDATE
               SET archived_at = NULL,
                   base_branch = EXCLUDED.base_branch,
                   ephemeral = EXCLUDED.ephemeral
            RETURNING id
            """, Integer.class,
            name,
            branch,
            volume,
            "team-" + teamId);
        return id;
    }

    private TeamRepoLink requireLink(int teamId, int linkId) {
        if (!teamExists(teamId)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Team not found");
        }
        return repoLinkRepository.findByIdAndTeamId(linkId, teamId)
            .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND,
                "Repository link not found"));
    }

    private Map<String, Boolean> nightHeavyModels(int teamId) {
        Map<String, Boolean> result = new HashMap<>();
        try {
            jdbc.query("""
                SELECT lower(m.name) AS model_name,
                       COALESCE(SUM(s.requests), 0) AS total_requests,
                       COALESCE(SUM(s.requests) FILTER (
                           WHERE EXTRACT(HOUR FROM s.bucket_hour AT TIME ZONE 'UTC') BETWEEN 0 AND 5
                       ), 0) AS night_requests
                  FROM log_entry_hourly_stats s
                  JOIN models m ON m.id = s.model_id
                 WHERE s.team_id = ?
                 GROUP BY lower(m.name)
                """,
                rs -> {
                    while (rs.next()) {
                        long total = rs.getLong("total_requests");
                        long night = rs.getLong("night_requests");
                        boolean nightHeavy = total > 0 && night * 2 > total;
                        result.put(rs.getString("model_name"), nightHeavy);
                    }
                    return null;
                },
                teamId);
        }
        catch (Exception ignored) {
            // Rollup may be empty in tests / fresh DBs — leave flags false.
        }
        return result;
    }

    static int slaToPriority(String sla) {
        return switch (sla) {
            case "ux-critical" -> 10;
            case "ux-background" -> 1;
            default -> 5;
        };
    }

    private static String workflowGroupName(String filePath) {
        int slash = filePath.indexOf('/');
        if (slash <= 0) {
            return filePath;
        }
        return filePath.substring(0, slash);
    }

    private static String buildCodeUrl(TeamRepoLink link, String commitSha, String filePath, int line) {
        String ref = (commitSha != null && !commitSha.isBlank() && !"unknown".equals(commitSha))
            ? commitSha
            : (link.getBranch() != null ? link.getBranch() : "main");
        return "https://github.com/" + link.getRepoSlug() + "/blob/" + ref + "/" + filePath + "#L" + line;
    }

    private Map<String, Object> analysisToMap(AiWorkflowAnalysis analysis) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", analysis.getId());
        m.put("team_id", analysis.getTeamId());
        m.put("team_repository_id", analysis.getTeamRepositoryId());
        m.put("commit_sha", analysis.getCommitSha());
        m.put("status", analysis.getStatus());
        m.put("source", analysis.getSource());
        m.put("agent_session_id", analysis.getAgentSessionId());
        m.put("error", analysis.getError());
        m.put("started_at", analysis.getStartedAt() != null ? analysis.getStartedAt().toString() : null);
        m.put("finished_at", analysis.getFinishedAt() != null ? analysis.getFinishedAt().toString() : null);
        return m;
    }

    private Map<String, Object> workflowToMap(AiWorkflow workflow) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", workflow.getId());
        m.put("analysis_id", workflow.getAnalysisId());
        m.put("name", workflow.getName());
        m.put("trigger_summary", workflow.getTriggerSummary());
        m.put("diagram_mermaid", workflow.getDiagramMermaid());
        m.put("sort_order", workflow.getSortOrder());
        return m;
    }

    private Map<String, Object> recommendationToMap(AiLlmCallRecommendation rec) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", rec.getId());
        m.put("analysis_id", rec.getAnalysisId());
        m.put("workflow_id", rec.getWorkflowId());
        m.put("team_id", rec.getTeamId());
        m.put("file_path", rec.getFilePath());
        m.put("start_line", rec.getStartLine());
        m.put("end_line", rec.getEndLine());
        m.put("code_url", rec.getCodeUrl());
        m.put("detected_model", rec.getDetectedModel());
        m.put("api_key_id", rec.getApiKeyId());
        m.put("recommended_sla", rec.getRecommendedSla());
        m.put("objective_priority", ObjectivePriority.asStringList(rec.getObjectivePriority()));
        m.put("confidence", rec.getConfidence());
        m.put("justification", rec.getJustification());
        m.put("traffic_flags", rec.getTrafficFlags());
        m.put("review_status", rec.getReviewStatus());
        m.put("confirmed_sla", rec.getConfirmedSla());
        m.put("confirmed_objective_priority",
            rec.getConfirmedObjectivePriority() != null
                ? ObjectivePriority.asStringList(rec.getConfirmedObjectivePriority())
                : null);
        m.put("reviewed_by", rec.getReviewedBy());
        m.put("reviewed_at", rec.getReviewedAt() != null ? rec.getReviewedAt().toString() : null);
        return m;
    }
}
