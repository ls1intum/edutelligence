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

import org.springframework.dao.DuplicateKeyException;
import org.springframework.data.domain.Sort;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.identity.ObjectivePriority;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.ReviewRecommendationRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.ReviewWorkflowDiagramProposalRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.SetRecommendationModelRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.SetWorkflowDiagramRequestDTO;
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

    private static final Set<String> VALID_SLOS = Set.of("ux-critical", "ux-high-prio", "ux-background");
    private static final int MAX_MODEL_NAME_LENGTH = 200;
    private static final int MAX_DIAGRAM_MERMAID_LENGTH = 100_000;
    private static final int MAX_ANCESTOR_HOPS = 50;
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final Set<String> REVIEW_ACTIONS = Set.of("accept", "override", "reject");
    private static final Set<String> DIAGRAM_PROPOSAL_ACTIONS = Set.of("accept", "dismiss");

    /**
     * Same contract as logos-agent {@code analysis_triggers.ANALYSIS_TASK}.
     */
    static final String ANALYSIS_TASK_TEMPLATE = """
        Analyse this linked application repository for AI / LLM call sites and produce
        workflow diagrams plus SLO recommendations.

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
              "recommended_slo": "ux-critical" | "ux-high-prio" | "ux-background",
              "objective_priority": ["latency" | "quality" | "price", "..."],
              "confidence": 0.0,
              "justification": "why this SLO and objective order",
              "traffic_flags": {"night_heavy": false}
            }
          ]
        }

        `diagram_mermaid` must parse with Mermaid 11: wrap every node and edge label
        in double quotes (`A["Session title LLM (deferred)"]`, `B{"EXERCISE mode?"}`,
        `A -->|"yes"| B`). Parentheses, brackets, braces, pipes or slashes inside an
        unquoted label are syntax errors and the diagram will not render.

        `objective_priority` is a full ranking of latency, quality, and price (most
        important first). It complements SLO: SLO is urgency/interactivity; the ranking
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
    private final RepoCredentialCrypto crypto;
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;

    public AiWorkflowAnalysisService(TeamMemberRepository teamMemberRepository,
                                     TeamRepository teamRepository,
                                     TeamRepoLinkRepository repoLinkRepository,
                                     TeamRepositoryCredentialRepository credentialRepository,
                                     AiWorkflowAnalysisRepository analysisRepository,
                                     AiWorkflowRepository workflowRepository,
                                     AiLlmCallRecommendationRepository recommendationRepository,
                                     ApiKeyRepository apiKeyRepository,
                                     ApiKeyAdminService apiKeyAdminService,
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
        this.crypto = crypto;
        this.jdbc = jdbc;
        this.tx = new TransactionTemplate(txManager);
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
        // Pending work is what the latest analyses propose; a superseded
        // analysis' unreviewed rows are not something to review any more.
        List<Map<String, Object>> pending = new ArrayList<>();
        for (TeamRepoLink link : links) {
            Map<String, Object> repo = new LinkedHashMap<>();
            repo.put("id", link.getId());
            repo.put("repo_slug", link.getRepoSlug());
            repo.put("repo_url", link.getRepoUrl());
            repo.put("branch", link.getBranch());

            Optional<AiWorkflowAnalysis> latest = analysisRepository.findLatestSucceeded(link.getId());
            if (latest.isPresent()) {
                AiWorkflowAnalysis analysis = latest.get();
                repo.put("latest_analysis", analysisToMap(analysis));
                List<AiWorkflow> workflows = workflowRepository
                    .findByAnalysisIdOrderBySortOrderAsc(analysis.getId());
                repo.put("workflows", workflows.stream().map(this::workflowToMap).toList());
                List<AiLlmCallRecommendation> recs = recommendationRepository
                    .findByAnalysisIdOrderByIdAsc(analysis.getId());
                Map<Integer, Map<String, Object>> decisions = previousDecisions(recs);
                List<Map<String, Object>> mapped = recs.stream()
                    .map(rec -> recommendationToMap(rec, decisions.get(rec.getId())))
                    .toList();
                repo.put("recommendations", mapped);
                mapped.stream().filter(m -> "pending".equals(m.get("review_status"))).forEach(pending::add);
            }
            else {
                repo.put("latest_analysis", null);
                repo.put("workflows", List.of());
                repo.put("recommendations", List.of());
            }
            repositories.add(repo);
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("team_id", teamId);
        result.put("repositories", repositories);
        result.put("pending_recommendations", pending);
        return result;
    }

    /**
     * Records which model a call site uses. Analyses often cannot tell — the
     * model is usually configuration, not code — so the owner says it. Allowed
     * in any review state: it describes the code, not the decision.
     */
    @Transactional
    public Map<String, Object> setRecommendationModel(int teamId, int recId,
                                                      SetRecommendationModelRequestDTO body) {
        AiLlmCallRecommendation rec = lockCurrentRecommendation(teamId, recId);
        String model = body == null || body.model() == null ? null : body.model().trim();
        if (model != null && model.length() > MAX_MODEL_NAME_LENGTH) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                "model must be at most " + MAX_MODEL_NAME_LENGTH + " characters");
        }
        rec.setDetectedModel(model == null || model.isEmpty() ? null : model);
        // Clearing is a decision too: the next analysis must not refill it.
        rec.setModelSetByOwner(true);
        recommendationRepository.save(rec);
        return recommendationToMap(rec);
    }

    /**
     * Saves an owner-edited Mermaid activity diagram. The next analysis keeps
     * this source and, when it differs, stores the agent's version as a
     * proposal instead of overwriting.
     */
    @Transactional
    public Map<String, Object> setWorkflowDiagram(int teamId, int workflowId,
                                                  SetWorkflowDiagramRequestDTO body) {
        AiWorkflow workflow = lockCurrentWorkflow(teamId, workflowId);
        if (body == null || body.diagramMermaid() == null || body.diagramMermaid().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "diagram_mermaid is required");
        }
        String diagram = body.diagramMermaid().strip();
        if (diagram.length() > MAX_DIAGRAM_MERMAID_LENGTH) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                "diagram_mermaid must be at most " + MAX_DIAGRAM_MERMAID_LENGTH + " characters");
        }
        workflow.setDiagramMermaid(diagram);
        workflow.setDiagramSetByOwner(true);
        // The owner's save is the confirmed diagram; drop any pending agent proposal.
        workflow.setProposedDiagramMermaid(null);
        workflowRepository.save(workflow);
        return workflowToMap(workflow);
    }

    /**
     * Accept the agent's proposed Mermaid (replace the owner's) or dismiss it
     * and keep the current diagram.
     */
    @Transactional
    public Map<String, Object> reviewWorkflowDiagramProposal(
            int teamId, int workflowId, ReviewWorkflowDiagramProposalRequestDTO body) {
        if (body == null || body.action() == null || body.action().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "action is required");
        }
        String action = body.action().trim().toLowerCase(Locale.ROOT);
        if (!DIAGRAM_PROPOSAL_ACTIONS.contains(action)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                "action must be accept or dismiss");
        }
        AiWorkflow workflow = lockCurrentWorkflow(teamId, workflowId);
        String proposed = workflow.getProposedDiagramMermaid();
        if (proposed == null || proposed.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                "No agent diagram proposal is pending for this workflow");
        }
        if ("accept".equals(action)) {
            workflow.setDiagramMermaid(proposed.strip());
            // Back under agent control: later analyses may update freely again.
            workflow.setDiagramSetByOwner(false);
            workflow.setDismissedDiagramMermaid(null);
        } else {
            // Keep mine: re-analyses drawing this same Mermaid do not propose it again.
            workflow.setDismissedDiagramMermaid(proposed);
        }
        workflow.setProposedDiagramMermaid(null);
        workflowRepository.save(workflow);
        return workflowToMap(workflow);
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

        AiLlmCallRecommendation rec = lockCurrentRecommendation(teamId, recId);

        Instant now = Instant.now();
        rec.setReviewCarriedOver(false);
        rec.setReviewedBy(reviewerUserId);
        rec.setReviewedAt(now);

        if ("reject".equals(action)) {
            rec.setReviewStatus("rejected");
            rec.setConfirmedSlo(null);
            rec.setConfirmedObjectivePriority(null);
            recommendationRepository.save(rec);
            return recommendationToMap(rec);
        }

        String confirmedSlo;
        List<Object> confirmedPriority;
        if ("accept".equals(action)) {
            confirmedSlo = rec.getRecommendedSlo();
            if (body.confirmedSlo() != null && !body.confirmedSlo().isBlank()) {
                confirmedSlo = body.confirmedSlo().trim();
            }
            confirmedPriority = ObjectivePriority.asJsonList(
                body.confirmedObjectivePriority() != null
                    ? body.confirmedObjectivePriority()
                    : ObjectivePriority.asStringList(rec.getObjectivePriority()));
            rec.setReviewStatus("accepted");
        }
        else {
            if (body.confirmedSlo() == null || body.confirmedSlo().isBlank()) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "confirmed_slo is required for override");
            }
            confirmedSlo = body.confirmedSlo().trim();
            confirmedPriority = ObjectivePriority.asJsonList(
                body.confirmedObjectivePriority() != null
                    ? body.confirmedObjectivePriority()
                    : ObjectivePriority.asStringList(rec.getObjectivePriority()));
            rec.setReviewStatus("overridden");
        }
        if (!VALID_SLOS.contains(confirmedSlo)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                "confirmed_slo must be ux-critical, ux-high-prio, or ux-background");
        }
        rec.setConfirmedSlo(confirmedSlo);
        rec.setConfirmedObjectivePriority(confirmedPriority);

        boolean noKey = Boolean.TRUE.equals(body.noApiKey());
        if (noKey) {
            rec.setApiKeyId(null);
        }
        Integer apiKeyId = noKey ? null : body.apiKeyId() != null ? body.apiKeyId() : rec.getApiKeyId();
        if (apiKeyId != null) {
            var key = apiKeyRepository.findById(apiKeyId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "API key not found: " + apiKeyId));
            if (key.getTeamId() == null || !key.getTeamId().equals(teamId)) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "API key does not belong to this team");
            }
            rec.setApiKeyId(apiKeyId);
            int priority = sloToPriority(confirmedSlo);
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
        if (!crypto.isConfigured()) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,
                "Private repository credentials are not enabled on this server");
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
    public Map<String, Object> queueAgentAnalysis(int teamId, int linkId) {
        TeamRepoLink link = requireLink(teamId, linkId);
        Map<String, Object> queued = queueUnlessInFlight(teamId, link);
        if (queued == null) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                "An analysis of " + link.getRepoSlug() + " is already queued or running");
        }
        return queued;
    }

    /**
     * Queue an analysis of every linked repository that has none in flight.
     * A manual run always analyses: it is how an admin gets fresh results
     * after the analysis task itself changed, even on an unchanged commit.
     */
    public Map<String, Object> queueAllAgentAnalyses() {
        List<String> queued = new ArrayList<>();
        List<String> inFlight = new ArrayList<>();
        for (TeamRepoLink link : repoLinkRepository.findAll(Sort.by("id"))) {
            if (queueUnlessInFlight(link.getTeamId(), link) == null) {
                inFlight.add(link.getRepoSlug());
            }
            else {
                queued.add(link.getRepoSlug());
            }
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("queued", queued.size());
        result.put("already_in_flight", inFlight.size());
        result.put("message", queued.size() + " analyses queued, " + inFlight.size() + " already in flight");
        return result;
    }

    /**
     * Queue one analysis in its own transaction, or return null when one is
     * already queued or running. The queued analysis row goes in first: the
     * partial unique index on in-flight analyses (Liquibase 050) admits one per
     * repository across this, the bulk path and the agent runner's nightly
     * pass, and a refused insert rolls back before any session exists.
     */
    private Map<String, Object> queueUnlessInFlight(int teamId, TeamRepoLink link) {
        try {
            return tx.execute(status -> queue(teamId, link));
        }
        catch (DuplicateKeyException e) {
            return null;
        }
    }

    private Map<String, Object> queue(int teamId, TeamRepoLink link) {
        Integer analysisId = jdbc.queryForObject("""
            INSERT INTO ai_workflow_analyses (team_id, team_repository_id, status, source, started_at)
            VALUES (?, ?, 'queued', 'agent', CURRENT_TIMESTAMP)
            RETURNING id
            """, Integer.class, teamId, link.getId());
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

        jdbc.update("UPDATE ai_workflow_analyses SET agent_session_id = ? WHERE id = ?", sessionId, analysisId);
        AiWorkflowAnalysis analysis = analysisRepository.findById(analysisId)
            .orElseThrow(() -> new IllegalStateException("queued analysis " + analysisId + " vanished"));

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

    static int sloToPriority(String slo) {
        return switch (slo) {
            case "ux-critical" -> 10;
            case "ux-background" -> 1;
            default -> 5;
        };
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
        m.put("diagram_set_by_owner", workflow.isDiagramSetByOwner());
        m.put("proposed_diagram_mermaid", workflow.getProposedDiagramMermaid());
        return m;
    }

    private Map<String, Object> recommendationToMap(AiLlmCallRecommendation rec) {
        return recommendationToMap(rec, previousDecisions(List.of(rec)).get(rec.getId()));
    }

    private Map<String, Object> recommendationToMap(AiLlmCallRecommendation rec, Map<String, Object> previous) {
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
        m.put("recommended_slo", rec.getRecommendedSlo());
        m.put("objective_priority", ObjectivePriority.asStringList(rec.getObjectivePriority()));
        m.put("confidence", rec.getConfidence());
        m.put("justification", rec.getJustification());
        m.put("traffic_flags", rec.getTrafficFlags());
        m.put("review_status", rec.getReviewStatus());
        m.put("confirmed_slo", rec.getConfirmedSlo());
        m.put("confirmed_objective_priority",
            rec.getConfirmedObjectivePriority() != null
                ? ObjectivePriority.asStringList(rec.getConfirmedObjectivePriority())
                : null);
        m.put("reviewed_by", rec.getReviewedBy());
        m.put("reviewed_at", rec.getReviewedAt() != null ? rec.getReviewedAt().toString() : null);
        m.put("model_set_by_owner", rec.isModelSetByOwner());
        m.put("review_carried_over", rec.isReviewCarriedOver());
        m.put("previous", previous);
        return m;
    }

    /**
     * Lock a recommendation for an owner edit, after its repository: the
     * agent ingest takes the repository lock before it reads the decisions it
     * carries over, so an edit either lands before that read or waits for the
     * new analysis. An edit to a recommendation a newer analysis superseded
     * is refused — the page is showing old proposals and must reload.
     */
    private AiLlmCallRecommendation lockCurrentRecommendation(int teamId, int recId) {
        Integer repoId = jdbc.query("""
            SELECT a.team_repository_id FROM ai_llm_call_recommendations r
              JOIN ai_workflow_analyses a ON a.id = r.analysis_id
             WHERE r.id = ? AND r.team_id = ?
            """, rs -> rs.next() ? (Integer) rs.getObject(1) : null, recId, teamId);
        if (repoId != null) {
            jdbc.query("SELECT id FROM team_repositories WHERE id = ? FOR UPDATE", rs -> null, repoId);
        }
        AiLlmCallRecommendation rec = recommendationRepository.lockByIdAndTeamId(recId, teamId)
            .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND,
                "Recommendation not found"));
        if (repoId != null) {
            Integer latest = analysisRepository.findLatestSucceeded(repoId).map(AiWorkflowAnalysis::getId).orElse(null);
            if (latest != null && !latest.equals(rec.getAnalysisId())) {
                throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "A newer analysis replaced this recommendation; reload the Workflows tab");
            }
        }
        return rec;
    }

    /**
     * Same repository-then-row lock as recommendations: ingest copies
     * owner-edited diagrams from the previous analysis under the repository
     * lock, so an edit either lands first or waits for the new analysis. An
     * edit on a workflow a newer analysis superseded is refused.
     */
    private AiWorkflow lockCurrentWorkflow(int teamId, int workflowId) {
        Integer repoId = jdbc.query("""
            SELECT a.team_repository_id FROM ai_workflows w
              JOIN ai_workflow_analyses a ON a.id = w.analysis_id
             WHERE w.id = ? AND a.team_id = ?
            """, rs -> rs.next() ? (Integer) rs.getObject(1) : null, workflowId, teamId);
        if (repoId == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Workflow not found");
        }
        jdbc.query("SELECT id FROM team_repositories WHERE id = ? FOR UPDATE", rs -> null, repoId);
        AiWorkflow workflow = workflowRepository.lockById(workflowId)
            .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND,
                "Workflow not found"));
        Integer latest = analysisRepository.findLatestSucceeded(repoId).map(AiWorkflowAnalysis::getId).orElse(null);
        if (latest != null && !latest.equals(workflow.getAnalysisId())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                "A newer analysis replaced this workflow; reload the Workflows tab");
        }
        return workflow;
    }

    /**
     * For each recommendation, the nearest predecessor the owner reviewed —
     * what a changed proposal is shown next to. Unreviewed analyses in between
     * are passed over, so an earlier decision is not lost because a proposal
     * sat pending while the next analysis ran. One recursive query for the
     * whole set (the agent ingest resolves the same chain the same way).
     */
    private Map<Integer, Map<String, Object>> previousDecisions(List<AiLlmCallRecommendation> recs) {
        Integer[] ids = recs.stream()
            .filter(r -> r.getId() != null && r.getPreviousRecommendationId() != null)
            .map(AiLlmCallRecommendation::getId)
            .toArray(Integer[]::new);
        Map<Integer, Map<String, Object>> result = new HashMap<>();
        if (ids.length == 0) return result;
        jdbc.query(con -> {
            var ps = con.prepareStatement("""
                WITH RECURSIVE chain AS (
                    SELECT r.id AS start_id, p.id, p.review_status, p.previous_recommendation_id, 1 AS depth
                      FROM ai_llm_call_recommendations r
                      JOIN ai_llm_call_recommendations p ON p.id = r.previous_recommendation_id
                     WHERE r.id = ANY(?)
                    UNION ALL
                    SELECT c.start_id, p.id, p.review_status, p.previous_recommendation_id, c.depth + 1
                      FROM chain c
                      JOIN ai_llm_call_recommendations p ON p.id = c.previous_recommendation_id
                     WHERE c.review_status = 'pending' AND c.depth < ?
                )
                SELECT DISTINCT ON (c.start_id) c.start_id, d.id, d.review_status,
                       COALESCE(d.confirmed_slo, d.recommended_slo) AS slo,
                       COALESCE(d.confirmed_objective_priority, d.objective_priority)::text AS priority,
                       d.reviewed_at
                  FROM chain c
                  JOIN ai_llm_call_recommendations d ON d.id = c.id
                 WHERE c.review_status <> 'pending'
                 ORDER BY c.start_id, c.depth
                """);
            ps.setArray(1, con.createArrayOf("integer", ids));
            ps.setInt(2, MAX_ANCESTOR_HOPS);
            return ps;
        }, rs -> {
            Map<String, Object> p = new LinkedHashMap<>();
            p.put("id", rs.getInt("id"));
            p.put("review_status", rs.getString("review_status"));
            p.put("slo", rs.getString("slo"));
            p.put("objective_priority", ObjectivePriority.asStringList(parseJsonList(rs.getString("priority"))));
            var reviewedAt = rs.getTimestamp("reviewed_at");
            p.put("reviewed_at", reviewedAt != null ? reviewedAt.toInstant().toString() : null);
            result.put(rs.getInt("start_id"), p);
        });
        return result;
    }

    private static List<Object> parseJsonList(String json) {
        if (json == null) return null;
        try {
            return JSON.readValue(json, new TypeReference<List<Object>>() { });
        }
        catch (JsonProcessingException e) {
            return null;
        }
    }
}
