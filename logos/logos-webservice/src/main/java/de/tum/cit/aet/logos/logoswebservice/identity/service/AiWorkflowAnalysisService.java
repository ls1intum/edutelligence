package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
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
import de.tum.cit.aet.logos.logoswebservice.identity.dto.SetRecommendationModelRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.StoreDeployKeyRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateApiKeyRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateWorkflowRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateWorkflowStepRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.WorkflowBenchmarkRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.AiLlmCallRecommendation;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.AiWorkflow;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.AiWorkflowAnalysis;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.AiWorkflowStep;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamRepoLink;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamRepositoryCredential;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.AiLlmCallRecommendationRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.AiWorkflowAnalysisRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.AiWorkflowRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.AiWorkflowStepRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepoLinkRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepositoryCredentialRepository;

@Service
public class AiWorkflowAnalysisService {

    private static final Set<String> VALID_SLAS = Set.of("ux-critical", "ux-high-prio", "ux-background");
    private static final Set<String> VALID_WORKFLOW_STATUSES = Set.of("active", "deprecated", "ignored");
    private static final int MAX_MODEL_NAME_LENGTH = 200;
    private static final int MAX_ANCESTOR_HOPS = 50;
    private static final int DEFAULT_BENCHMARK_SAMPLE_SIZE = 50;
    private static final int MAX_BENCHMARK_SAMPLE_SIZE = 200;
    private static final int MAX_TAG_LENGTH = 80;
    /** Room kept for a "-N" suffix that makes a generated tag unique. */
    private static final int TAG_SUFFIX_RESERVE = 6;
    private static final ObjectMapper JSON = new ObjectMapper();
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
              "sort_order": 0,
              "tag": "<stable kebab-case tag for X-Logos-Workflow-Tag, or null>",
              "steps": [
                {
                  "name": "<short step name>",
                  "sort_order": 0,
                  "tag": "<stable kebab-case tag for X-Logos-Workflow-Tag>",
                  "recommended_sla": "ux-critical" | "ux-high-prio" | "ux-background",
                  "objective_priority": ["latency" | "quality" | "price", "..."]
                }
              ]
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

        `diagram_mermaid` must parse with Mermaid 11: wrap every node and edge label
        in double quotes (`A["Session title LLM (deferred)"]`, `B{"EXERCISE mode?"}`,
        `A -->|"yes"| B`). Parentheses, brackets, braces, pipes or slashes inside an
        unquoted label are syntax errors and the diagram will not render.

        `objective_priority` is a full ranking of latency, quality, and price (most
        important first). It complements SLA: SLA is urgency/interactivity; the ranking
        says what to optimize for when choosing a model. If omitted, defaults are:
        ux-critical → [latency, quality, price]; ux-high-prio → [quality, latency, price];
        ux-background → [price, quality, latency].

        Suggest stable kebab-case `tag` values on workflows and steps so applications
        can send `X-Logos-Workflow-Tag` (and optionally `X-Logos-SLA`) to attribute
        traffic. Prefer short, unique tags derived from the workflow/step name.

        Repository: %s
        Clone URL: %s
        Focus paths (empty means whole tree): %s
        """;

    static final String TAGGING_PR_TASK_TEMPLATE = """
        Add request attribution headers at the LLM call sites that belong to this
        Logos workflow so traffic can be matched to the workflow and its steps.

        Workflow: %s
        Workflow tag (X-Logos-Workflow-Tag): %s

        Steps (send the step tag as X-Logos-Workflow-Tag when the call is that step;
        also set X-Logos-SLA to the confirmed or recommended SLA when known):
        %s

        Repository: %s
        Clone URL: %s

        Use these tag values exactly as written; Logos matches them verbatim.
        Open a pull request with the header changes. Prefer the smallest clear
        change that wires tags at each matching call site; do not refactor
        unrelated code.
        """;

    private final TeamMemberRepository teamMemberRepository;
    private final TeamRepository teamRepository;
    private final TeamRepoLinkRepository repoLinkRepository;
    private final TeamRepositoryCredentialRepository credentialRepository;
    private final AiWorkflowAnalysisRepository analysisRepository;
    private final AiWorkflowRepository workflowRepository;
    private final AiWorkflowStepRepository stepRepository;
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
                                     AiWorkflowStepRepository stepRepository,
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
        this.stepRepository = stepRepository;
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
                    .findByAnalysisIdOrderBySortOrderAsc(analysis.getId())
                    .stream()
                    .filter(w -> w.getDeletedAt() == null)
                    .toList();
                Map<Integer, List<AiWorkflowStep>> stepsByWorkflow = stepsByWorkflowIds(
                    workflows.stream().map(AiWorkflow::getId).toList());
                repo.put("workflows", workflows.stream()
                    .map(w -> workflowToMap(w, stepsByWorkflow.getOrDefault(w.getId(), List.of())))
                    .toList());
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

    @Transactional
    public Map<String, Object> updateWorkflow(int teamId, int workflowId, UpdateWorkflowRequestDTO body) {
        if (body == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "body is required");
        }
        AiWorkflow workflow = lockCurrentWorkflow(teamId, workflowId);
        if (body.status() != null) {
            String status = body.status().trim().toLowerCase(Locale.ROOT);
            if (!VALID_WORKFLOW_STATUSES.contains(status)) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "status must be active, deprecated, or ignored");
            }
            workflow.setStatus(status);
        }
        if (body.tag() != null) {
            workflow.setTag(claimTag(teamId, workflow.getTag(), normalizeTag(body.tag())));
        }
        if (Boolean.TRUE.equals(body.deleted())) {
            workflow.setDeletedAt(Instant.now());
            workflow.setStatus("ignored");
        }
        else if (Boolean.FALSE.equals(body.deleted())) {
            workflow.setDeletedAt(null);
            if (body.status() == null || "active".equalsIgnoreCase(body.status().trim())) {
                workflow.setStatus("active");
            }
        }
        workflowRepository.save(workflow);
        return workflowToMap(workflow, stepRepository.findByWorkflowIdOrderBySortOrderAsc(workflow.getId()));
    }

    @Transactional
    public Map<String, Object> updateWorkflowStep(int teamId, int stepId, UpdateWorkflowStepRequestDTO body) {
        if (body == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "body is required");
        }
        AiWorkflowStep step = lockCurrentStep(teamId, stepId);
        if (body.confirmedSla() != null) {
            String sla = body.confirmedSla().trim();
            if (sla.isEmpty()) {
                step.setConfirmedSla(null);
            }
            else {
                if (!VALID_SLAS.contains(sla)) {
                    throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                        "confirmed_sla must be ux-critical, ux-high-prio, or ux-background");
                }
                step.setConfirmedSla(sla);
            }
        }
        if (body.confirmedObjectivePriority() != null) {
            step.setConfirmedObjectivePriority(ObjectivePriority.asJsonList(body.confirmedObjectivePriority()));
        }
        if (body.tag() != null) {
            step.setTag(claimTag(teamId, step.getTag(), normalizeTag(body.tag())));
        }
        if (body.name() != null) {
            String name = body.name().trim();
            if (name.isEmpty()) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "name must not be blank");
            }
            step.setName(name);
        }
        stepRepository.save(step);
        return stepToMap(step);
    }

    @Transactional
    public Map<String, Object> compareWorkflow(int teamId, int workflowId,
                                              WorkflowBenchmarkRequestDTO body, Integer userId) {
        AiWorkflow workflow = requireWorkflowForTeam(teamId, workflowId);
        if (body == null || body.candidateModel() == null || body.candidateModel().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "candidate_model is required");
        }
        String candidateModel = body.candidateModel().trim();
        if (candidateModel.length() > MAX_MODEL_NAME_LENGTH) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                "candidate_model must be at most " + MAX_MODEL_NAME_LENGTH + " characters");
        }
        int sampleSize = body.sampleSize() == null ? DEFAULT_BENCHMARK_SAMPLE_SIZE : body.sampleSize();
        if (sampleSize < 1) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "sample_size must be at least 1");
        }
        sampleSize = Math.min(sampleSize, MAX_BENCHMARK_SAMPLE_SIZE);

        List<AiWorkflowStep> steps = stepRepository.findByWorkflowIdOrderBySortOrderAsc(workflow.getId());
        List<String> tags = new ArrayList<>();
        if (workflow.getTag() != null && !workflow.getTag().isBlank()) {
            tags.add(workflow.getTag().trim());
        }
        for (AiWorkflowStep step : steps) {
            if (step.getTag() != null && !step.getTag().isBlank()) {
                tags.add(step.getTag().trim());
            }
        }

        Map<String, Object> historicMetrics = computeHistoricMetrics(teamId, workflow.getId(), tags, sampleSize);
        Map<String, Object> candidateMetrics = new LinkedHashMap<>();
        candidateMetrics.put("candidate_model", candidateModel);
        candidateMetrics.put("note",
            "Historic sample only — re-run traffic with the candidate model to fill live metrics.");

        String historicJson = toJson(historicMetrics);
        String candidateJson = toJson(candidateMetrics);
        Integer benchmarkId = jdbc.queryForObject("""
            INSERT INTO ai_workflow_benchmarks (
                workflow_id, team_id, candidate_model, status, sample_size,
                historic_metrics, candidate_metrics, created_by, finished_at
            ) VALUES (
                ?, ?, ?, 'succeeded', ?,
                ?::jsonb, ?::jsonb, ?, CURRENT_TIMESTAMP
            ) RETURNING id
            """, Integer.class,
            workflow.getId(), teamId, candidateModel, sampleSize,
            historicJson, candidateJson, userId);

        return loadBenchmark(benchmarkId);
    }

    public List<Map<String, Object>> listWorkflowBenchmarks(int teamId, int workflowId) {
        requireWorkflowForTeam(teamId, workflowId);
        return jdbc.query("""
            SELECT id, workflow_id, team_id, candidate_model, status, sample_size,
                   historic_metrics, candidate_metrics, error, created_by, created_at, finished_at
              FROM ai_workflow_benchmarks
             WHERE workflow_id = ? AND team_id = ?
             ORDER BY created_at DESC
            """, (rs, rowNum) -> benchmarkRowToMap(rs), workflowId, teamId);
    }

    @Transactional
    public Map<String, Object> queueTaggingPullRequest(int teamId, int workflowId) {
        AiWorkflow workflow = lockCurrentWorkflow(teamId, workflowId);
        AiWorkflowAnalysis analysis = analysisRepository.findById(workflow.getAnalysisId())
            .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Analysis not found"));
        TeamRepoLink link = requireLink(teamId, analysis.getTeamRepositoryId());
        List<AiWorkflowStep> steps = stepRepository.findByWorkflowIdOrderBySortOrderAsc(workflow.getId());
        // The session only changes the application repository; its result is
        // never ingested. Tags it would invent could match nothing, so every
        // missing tag is fixed here first and the task names the stored values.
        assignMissingTags(teamId, workflow, steps);

        String stepsLabel = steps.isEmpty()
            ? "(no steps recorded — send the workflow tag at every call site)"
            : steps.stream()
                .map(s -> "- " + s.getName()
                    + " | tag=" + s.getTag()
                    + " | sla=" + (s.getConfirmedSla() != null ? s.getConfirmedSla() : s.getRecommendedSla()))
                .collect(Collectors.joining("\n"));

        String task = TAGGING_PR_TASK_TEMPLATE.formatted(
            workflow.getName(),
            workflow.getTag(),
            stepsLabel,
            link.getRepoSlug(),
            link.getRepoUrl());

        int workspaceId = ensureAnalysisWorkspace(teamId, link);
        Integer sessionId = jdbc.queryForObject("""
            INSERT INTO agent_sessions (
                workspace_id, task, model, status, created_by,
                open_pull_request, deploy_to_dev, screenshot_paths,
                no_push, trigger_kind, trigger_ref,
                repo_url, repo_slug, team_repository_id, priority, priority_reason
            ) VALUES (
                ?, ?, NULL, 'queued', ?,
                TRUE, FALSE, '[]'::jsonb,
                FALSE, 'workflow-tagging', ?,
                ?, ?, ?, 50, 'workflow tagging PR'
            ) RETURNING id
            """, Integer.class,
            workspaceId,
            task,
            "team-" + teamId,
            "workflow:" + workflow.getId(),
            link.getRepoUrl(),
            link.getRepoSlug(),
            link.getId());

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("agent_session_id", sessionId);
        result.put("workflow_id", workflow.getId());
        result.put("team_repository_id", link.getId());
        result.put("repo_slug", link.getRepoSlug());
        result.put("status", "queued");
        result.put("open_pull_request", true);
        result.put("no_push", false);
        result.put("message", "Tagging pull-request session queued");
        return result;
    }

    private Map<String, Object> computeHistoricMetrics(int teamId, int workflowId,
                                                       List<String> tags, int sampleSize) {
        List<Map<String, Object>> rows = jdbc.query(con -> {
            var ps = con.prepareStatement("""
                SELECT le.queue_wait_ms,
                       le.time_at_first_token,
                       le.timestamp_forwarding,
                       le.timestamp_request,
                       le.timestamp_response,
                       COALESCE(le.model_name, m.name) AS model_name
                  FROM log_entry le
                  LEFT JOIN models m ON m.id = le.model_id
                 WHERE le.team_id = ?
                   AND (le.workflow_id = ?
                        OR (cardinality(?) > 0 AND le.workflow_tag = ANY(?)))
                 ORDER BY le.timestamp_request DESC NULLS LAST
                 LIMIT ?
                """);
            ps.setInt(1, teamId);
            ps.setInt(2, workflowId);
            var tagArray = con.createArrayOf("text", tags.toArray());
            ps.setArray(3, tagArray);
            ps.setArray(4, tagArray);
            ps.setInt(5, sampleSize);
            return ps;
        }, (rs, rowNum) -> {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("queue_wait_ms", rs.getObject("queue_wait_ms") != null ? rs.getDouble("queue_wait_ms") : null);
            Instant requestAt = rs.getTimestamp("timestamp_request") != null
                ? rs.getTimestamp("timestamp_request").toInstant() : null;
            Instant forwardingAt = rs.getTimestamp("timestamp_forwarding") != null
                ? rs.getTimestamp("timestamp_forwarding").toInstant() : null;
            Instant ttftAt = rs.getTimestamp("time_at_first_token") != null
                ? rs.getTimestamp("time_at_first_token").toInstant() : null;
            Instant responseAt = rs.getTimestamp("timestamp_response") != null
                ? rs.getTimestamp("timestamp_response").toInstant() : null;
            Double ttftMs = null;
            if (ttftAt != null) {
                Instant base = forwardingAt != null ? forwardingAt : requestAt;
                if (base != null) {
                    ttftMs = (double) java.time.Duration.between(base, ttftAt).toMillis();
                }
            }
            Double latencyMs = null;
            if (requestAt != null && responseAt != null) {
                latencyMs = (double) java.time.Duration.between(requestAt, responseAt).toMillis();
            }
            row.put("ttft_ms", ttftMs);
            row.put("latency_ms", latencyMs);
            row.put("model_name", rs.getString("model_name"));
            return row;
        });

        List<Double> queueWaits = rows.stream()
            .map(r -> (Double) r.get("queue_wait_ms"))
            .filter(v -> v != null)
            .toList();
        List<Double> ttfts = rows.stream()
            .map(r -> (Double) r.get("ttft_ms"))
            .filter(v -> v != null)
            .toList();
        List<Double> latencies = rows.stream()
            .map(r -> (Double) r.get("latency_ms"))
            .filter(v -> v != null)
            .sorted()
            .toList();
        List<String> modelsSeen = rows.stream()
            .map(r -> (String) r.get("model_name"))
            .filter(n -> n != null && !n.isBlank())
            .distinct()
            .sorted()
            .toList();

        Map<String, Object> metrics = new LinkedHashMap<>();
        metrics.put("sample_count", rows.size());
        metrics.put("avg_queue_wait_ms", average(queueWaits));
        metrics.put("avg_ttft_ms", average(ttfts));
        metrics.put("models_seen", modelsSeen);
        metrics.put("p50_latency_ms", percentile(latencies, 0.50));
        metrics.put("p95_latency_ms", percentile(latencies, 0.95));
        return metrics;
    }

    private static Double average(List<Double> values) {
        if (values == null || values.isEmpty()) {
            return null;
        }
        double sum = 0;
        for (Double v : values) {
            sum += v;
        }
        return sum / values.size();
    }

    private static Double percentile(List<Double> sorted, double p) {
        if (sorted == null || sorted.isEmpty()) {
            return null;
        }
        if (sorted.size() == 1) {
            return sorted.get(0);
        }
        double rank = p * (sorted.size() - 1);
        int low = (int) Math.floor(rank);
        int high = (int) Math.ceil(rank);
        if (low == high) {
            return sorted.get(low);
        }
        double weight = rank - low;
        return sorted.get(low) * (1 - weight) + sorted.get(high) * weight;
    }

    private Map<String, Object> loadBenchmark(Integer id) {
        List<Map<String, Object>> rows = jdbc.query("""
            SELECT id, workflow_id, team_id, candidate_model, status, sample_size,
                   historic_metrics, candidate_metrics, error, created_by, created_at, finished_at
              FROM ai_workflow_benchmarks
             WHERE id = ?
            """, (rs, rowNum) -> benchmarkRowToMap(rs), id);
        if (rows.isEmpty()) {
            throw new IllegalStateException("benchmark " + id + " vanished");
        }
        return rows.get(0);
    }

    private Map<String, Object> benchmarkRowToMap(java.sql.ResultSet rs) throws java.sql.SQLException {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", rs.getInt("id"));
        m.put("workflow_id", rs.getInt("workflow_id"));
        m.put("team_id", rs.getInt("team_id"));
        m.put("candidate_model", rs.getString("candidate_model"));
        m.put("status", rs.getString("status"));
        m.put("sample_size", rs.getInt("sample_size"));
        m.put("historic_metrics", parseJsonObject(rs.getObject("historic_metrics")));
        m.put("candidate_metrics", parseJsonObject(rs.getObject("candidate_metrics")));
        m.put("error", rs.getString("error"));
        m.put("created_by", rs.getObject("created_by") != null ? rs.getInt("created_by") : null);
        var createdAt = rs.getTimestamp("created_at");
        m.put("created_at", createdAt != null ? createdAt.toInstant().toString() : null);
        var finishedAt = rs.getTimestamp("finished_at");
        m.put("finished_at", finishedAt != null ? finishedAt.toInstant().toString() : null);
        return m;
    }

    private AiWorkflow requireWorkflowForTeam(int teamId, int workflowId) {
        if (!teamExists(teamId)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Team not found");
        }
        Integer foundTeamId = jdbc.query("""
            SELECT a.team_id
              FROM ai_workflows w
              JOIN ai_workflow_analyses a ON a.id = w.analysis_id
             WHERE w.id = ?
            """, rs -> rs.next() ? (Integer) rs.getObject(1) : null, workflowId);
        if (foundTeamId == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Workflow not found");
        }
        if (!foundTeamId.equals(teamId)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Workflow not found");
        }
        return workflowRepository.findById(workflowId)
            .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Workflow not found"));
    }

    /**
     * Lock a workflow for an owner edit, after its repository — the same
     * order and reason as {@link #lockCurrentRecommendation}: the agent ingest
     * takes the repository lock before it reads the lifecycle and step SLAs
     * it carries over, so an edit either lands before that read or waits for
     * the new analysis. An edit to a workflow a newer analysis superseded is
     * refused — the page is showing old workflows and must reload.
     */
    private AiWorkflow lockCurrentWorkflow(int teamId, int workflowId) {
        if (!teamExists(teamId)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Team not found");
        }
        // Identity only, by plain query: the entity is loaded after the lock,
        // so a concurrent edit that held it is seen rather than overwritten.
        Map<String, Object> owner = jdbc.query("""
            SELECT a.id AS analysis_id, a.team_id, a.team_repository_id
              FROM ai_workflows w
              JOIN ai_workflow_analyses a ON a.id = w.analysis_id
             WHERE w.id = ?
            """, rs -> {
                if (!rs.next()) {
                    return null;
                }
                Map<String, Object> row = new HashMap<>();
                row.put("analysis_id", rs.getObject("analysis_id"));
                row.put("team_id", rs.getObject("team_id"));
                row.put("team_repository_id", rs.getObject("team_repository_id"));
                return row;
            }, workflowId);
        if (owner == null || !Integer.valueOf(teamId).equals(owner.get("team_id"))) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Workflow not found");
        }
        Integer repoId = (Integer) owner.get("team_repository_id");
        if (repoId != null) {
            jdbc.query("SELECT id FROM team_repositories WHERE id = ? FOR UPDATE", rs -> null, repoId);
            Integer latest = analysisRepository.findLatestSucceeded(repoId)
                .map(AiWorkflowAnalysis::getId).orElse(null);
            if (latest != null && !latest.equals(owner.get("analysis_id"))) {
                throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "A newer analysis replaced this workflow; reload the Workflows tab");
            }
        }
        return workflowRepository.findById(workflowId)
            .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Workflow not found"));
    }

    /** Lock a step's workflow as {@link #lockCurrentWorkflow} does, then load the step. */
    private AiWorkflowStep lockCurrentStep(int teamId, int stepId) {
        Integer workflowId = jdbc.query("SELECT workflow_id FROM ai_workflow_steps WHERE id = ?",
            rs -> rs.next() ? (Integer) rs.getObject(1) : null, stepId);
        if (workflowId == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Workflow step not found");
        }
        try {
            lockCurrentWorkflow(teamId, workflowId);
        }
        catch (ResponseStatusException e) {
            if (e.getStatusCode() == HttpStatus.NOT_FOUND) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Workflow step not found");
            }
            throw e;
        }
        return stepRepository.findById(stepId)
            .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Workflow step not found"));
    }

    private Map<Integer, List<AiWorkflowStep>> stepsByWorkflowIds(List<Integer> workflowIds) {
        if (workflowIds == null || workflowIds.isEmpty()) {
            return Map.of();
        }
        return stepRepository.findByWorkflowIdInOrderByWorkflowIdAscSortOrderAsc(workflowIds)
            .stream()
            .collect(Collectors.groupingBy(AiWorkflowStep::getWorkflowId, LinkedHashMap::new, Collectors.toList()));
    }

    private static String toJson(Object value) {
        try {
            return JSON.writeValueAsString(value);
        }
        catch (JsonProcessingException e) {
            throw new IllegalStateException("Failed to serialize JSON", e);
        }
    }

    private static Object parseJsonObject(Object value) {
        String text;
        if (value != null && "org.postgresql.util.PGobject".equals(value.getClass().getName())) {
            try {
                text = (String) value.getClass().getMethod("getValue").invoke(value);
            }
            catch (ReflectiveOperationException e) {
                text = value.toString();
            }
        }
        else if (value instanceof String s) {
            text = s;
        }
        else {
            return value;
        }
        if (text == null || text.isBlank()) {
            return null;
        }
        try {
            return JSON.readValue(text, new TypeReference<Map<String, Object>>() { });
        }
        catch (JsonProcessingException e) {
            return text;
        }
    }

    private void assignMissingTags(int teamId, AiWorkflow workflow, List<AiWorkflowStep> steps) {
        Set<String> taken = lockTeamTags(teamId);
        if (workflow.getTag() == null || workflow.getTag().isBlank()) {
            workflow.setTag(uniqueTag(slugOrDefault(workflow.getName(), "workflow-" + workflow.getId()), taken));
            workflowRepository.save(workflow);
        }
        for (AiWorkflowStep step : steps) {
            if (step.getTag() == null || step.getTag().isBlank()) {
                String base = workflow.getTag() + "-" + slugOrDefault(step.getName(), "step-" + step.getId());
                step.setTag(uniqueTag(base, taken));
                stepRepository.save(step);
            }
        }
    }

    /**
     * Serialize tag changes of one team and return the tags its current
     * workflows and steps hold — the namespace both request resolvers match
     * in (each repository's latest succeeded analysis).
     */
    private Set<String> lockTeamTags(int teamId) {
        jdbc.query("SELECT pg_advisory_xact_lock(hashtext('ai-workflow-tags'), ?)", rs -> null, teamId);
        List<String> tags = jdbc.queryForList("""
            WITH current_analyses AS (
                SELECT a.id FROM ai_workflow_analyses a
                 WHERE a.team_id = ?
                   AND a.id = (
                         SELECT latest.id FROM ai_workflow_analyses latest
                          WHERE latest.team_repository_id = a.team_repository_id
                            AND latest.status = 'succeeded'
                          ORDER BY latest.finished_at DESC NULLS LAST, latest.id DESC
                          LIMIT 1
                       )
            )
            SELECT w.tag FROM ai_workflows w
             WHERE w.analysis_id IN (SELECT id FROM current_analyses) AND w.tag IS NOT NULL
            UNION
            SELECT s.tag FROM ai_workflow_steps s
              JOIN ai_workflows w ON w.id = s.workflow_id
             WHERE w.analysis_id IN (SELECT id FROM current_analyses) AND s.tag IS NOT NULL
            """, String.class, teamId);
        return new HashSet<>(tags);
    }

    /**
     * An owner-chosen tag must stay unique among the team's current workflows
     * and steps: both resolvers would otherwise attribute requests to
     * whichever match they find first.
     */
    private String claimTag(int teamId, String current, String wanted) {
        if (wanted == null || wanted.equals(current)) {
            return wanted;
        }
        if (lockTeamTags(teamId).contains(wanted)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                "tag " + wanted + " is already used by another workflow or step of this team");
        }
        return wanted;
    }

    /** {@code base}, or {@code base-2}, {@code base-3}, … — never one in {@code taken}; reserves it. */
    static String uniqueTag(String base, Set<String> taken) {
        String stem = base.length() > MAX_TAG_LENGTH - TAG_SUFFIX_RESERVE
            ? base.substring(0, MAX_TAG_LENGTH - TAG_SUFFIX_RESERVE).replaceAll("-+$", "")
            : base;
        String candidate = stem;
        for (int n = 2; taken.contains(candidate); n++) {
            candidate = stem + "-" + n;
        }
        taken.add(candidate);
        return candidate;
    }

    private static String slugOrDefault(String name, String fallback) {
        String slug = name == null ? "" : name.trim().toLowerCase(Locale.ROOT)
            .replaceAll("[^a-z0-9]+", "-")
            .replaceAll("^-+|-+$", "");
        return slug.isEmpty() ? fallback : slug;
    }

    /**
     * Same shape the analysis ingest produces: lowercase kebab-case, at most
     * {@value #MAX_TAG_LENGTH} characters. Blank clears the tag.
     */
    static String normalizeTag(String raw) {
        String trimmed = raw.trim();
        if (trimmed.isEmpty()) {
            return null;
        }
        String cleaned = trimmed.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9-]", "");
        if (cleaned.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                "tag must contain lowercase letters, digits, or hyphens");
        }
        return cleaned.length() > MAX_TAG_LENGTH ? cleaned.substring(0, MAX_TAG_LENGTH) : cleaned;
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

    static int slaToPriority(String sla) {
        return switch (sla) {
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

    private Map<String, Object> workflowToMap(AiWorkflow workflow, List<AiWorkflowStep> steps) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", workflow.getId());
        m.put("analysis_id", workflow.getAnalysisId());
        m.put("name", workflow.getName());
        m.put("trigger_summary", workflow.getTriggerSummary());
        m.put("diagram_mermaid", workflow.getDiagramMermaid());
        m.put("sort_order", workflow.getSortOrder());
        m.put("status", workflow.getStatus());
        m.put("deleted_at", workflow.getDeletedAt() != null ? workflow.getDeletedAt().toString() : null);
        m.put("tag", workflow.getTag());
        m.put("steps", steps == null ? List.of() : steps.stream().map(this::stepToMap).toList());
        return m;
    }

    private Map<String, Object> stepToMap(AiWorkflowStep step) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", step.getId());
        m.put("workflow_id", step.getWorkflowId());
        m.put("name", step.getName());
        m.put("sort_order", step.getSortOrder());
        m.put("tag", step.getTag());
        m.put("recommended_sla", step.getRecommendedSla());
        m.put("confirmed_sla", step.getConfirmedSla());
        m.put("objective_priority", ObjectivePriority.asStringList(step.getObjectivePriority()));
        m.put("confirmed_objective_priority",
            step.getConfirmedObjectivePriority() != null
                ? ObjectivePriority.asStringList(step.getConfirmedObjectivePriority())
                : null);
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
        m.put("step_id", rec.getStepId());
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
                       COALESCE(d.confirmed_sla, d.recommended_sla) AS sla,
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
            p.put("sla", rs.getString("sla"));
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
