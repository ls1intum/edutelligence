package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import de.tum.cit.aet.logos.logoswebservice.identity.dto.CreateTeamRepoLinkRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateTeamRepoLinkRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.AiWorkflowAnalysis;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamRepoLink;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.AiWorkflowAnalysisRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepoLinkRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepositoryCredentialRepository;
import jakarta.persistence.EntityManager;

@Service
public class TeamRepoLinkService {

    // https://github.com/owner/repo[.git][/...] or git@github.com:owner/repo[.git]
    private static final Pattern GITHUB_HTTPS = Pattern.compile(
        "^https?://(?:www\\.)?github\\.com/([^/\\s]+)/([^/\\s#?]+?)(?:\\.git)?/?$",
        Pattern.CASE_INSENSITIVE);
    private static final Pattern GITHUB_SSH = Pattern.compile(
        "^git@github\\.com:([^/\\s]+)/([^/\\s#?]+?)(?:\\.git)?/?$",
        Pattern.CASE_INSENSITIVE);

    private static final String UNIQUE_TEAM_SLUG = "uq_team_repositories_team_slug";

    private final TeamRepoLinkRepository repoLinkRepository;
    private final TeamRepository teamRepository;
    private final TeamMemberRepository teamMemberRepository;
    private final TeamRepositoryCredentialRepository credentialRepository;
    private final AiWorkflowAnalysisRepository analysisRepository;
    private final EntityManager entityManager;

    public TeamRepoLinkService(TeamRepoLinkRepository repoLinkRepository,
                               TeamRepository teamRepository,
                               TeamMemberRepository teamMemberRepository,
                               TeamRepositoryCredentialRepository credentialRepository,
                               AiWorkflowAnalysisRepository analysisRepository,
                               EntityManager entityManager) {
        this.repoLinkRepository = repoLinkRepository;
        this.teamRepository = teamRepository;
        this.teamMemberRepository = teamMemberRepository;
        this.credentialRepository = credentialRepository;
        this.analysisRepository = analysisRepository;
        this.entityManager = entityManager;
    }

    public boolean isTeamOwner(int teamId, int userId) {
        return teamMemberRepository.isOwner(teamId, userId);
    }

    public boolean teamExists(int teamId) {
        return teamRepository.existsById(teamId);
    }

    public List<Map<String, Object>> listForTeam(int teamId) {
        return repoLinkRepository.findByTeamIdOrderByRepoSlugAsc(teamId).stream()
            .map(this::toMap)
            .toList();
    }

    @Transactional
    public Map<String, Object> create(int teamId, CreateTeamRepoLinkRequestDTO body) {
        if (!teamExists(teamId)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Team not found");
        }
        String url = requireUrl(body.repoUrl());
        String slug = parseGithubSlug(url)
            .orElseThrow(() -> new ResponseStatusException(
                HttpStatus.BAD_REQUEST,
                "repo_url must be a GitHub repository URL (https://github.com/owner/repo or git@github.com:owner/repo.git)"));
        if (repoLinkRepository.existsByTeamIdAndRepoSlug(teamId, slug)) {
            throw duplicateSlug(slug);
        }
        Instant now = Instant.now();
        TeamRepoLink link = new TeamRepoLink();
        link.setTeamId(teamId);
        link.setRepoUrl(canonicalHttpsUrl(slug));
        link.setRepoSlug(slug);
        link.setBranch(normalizeBranch(body.branch()));
        link.setPaths(normalizePaths(body.paths()));
        link.setCreatedAt(now);
        link.setUpdatedAt(now);
        return toMap(saveLink(link, slug));
    }

    @Transactional
    public Optional<Map<String, Object>> update(int teamId, int linkId, UpdateTeamRepoLinkRequestDTO body) {
        // Lock before invalidating analyses so concurrent ingest cannot insert
        // a succeeded row against the old slug after our delete selection.
        Optional<TeamRepoLink> existing = repoLinkRepository.findByIdAndTeamIdForUpdate(linkId, teamId);
        if (existing.isEmpty()) {
            return Optional.empty();
        }
        TeamRepoLink link = existing.get();
        String previousSlug = link.getRepoSlug();
        String conflictSlug = previousSlug;
        if (body.repoUrl() != null) {
            String url = requireUrl(body.repoUrl());
            String slug = parseGithubSlug(url)
                .orElseThrow(() -> new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "repo_url must be a GitHub repository URL (https://github.com/owner/repo or git@github.com:owner/repo.git)"));
            if (repoLinkRepository.existsByTeamIdAndRepoSlugAndIdNot(teamId, slug, linkId)) {
                throw duplicateSlug(slug);
            }
            link.setRepoUrl(canonicalHttpsUrl(slug));
            link.setRepoSlug(slug);
            conflictSlug = slug;
            // Analyses are keyed by link id; a slug change means they describe
            // a different repository and must not stay as "latest succeeded"
            // coverage for the new URL.
            if (!slug.equals(previousSlug)) {
                analysisRepository.deleteByTeamRepositoryId(linkId);
                cancelOrphanedAnalysisSessions(linkId);
            }
        }
        if (body.branch() != null) {
            link.setBranch(normalizeBranch(body.branch()));
        }
        if (body.paths() != null) {
            link.setPaths(normalizePaths(body.paths()));
        }
        link.setUpdatedAt(Instant.now());
        return Optional.of(toMap(saveLink(link, conflictSlug)));
    }

    @Transactional
    public boolean delete(int teamId, int linkId) {
        Optional<TeamRepoLink> existing = repoLinkRepository.findByIdAndTeamIdForUpdate(linkId, teamId);
        if (existing.isEmpty()) {
            return false;
        }
        // Cancel before ON DELETE SET NULL so we still match on the link id.
        cancelOrphanedAnalysisSessions(linkId);
        repoLinkRepository.delete(existing.get());
        return true;
    }

    /**
     * Queued analysis can be cancelled in-database (no container yet). Active
     * sessions must keep occupying their workspace until the agent runner
     * honors {@code cancel_requested:} via {@code SessionManager.cancel},
     * which stops helpers and agent containers before freeing occupancy.
     */
    private void cancelOrphanedAnalysisSessions(int linkId) {
        entityManager.createNativeQuery("""
            UPDATE agent_sessions
               SET status = 'cancelled',
                   error = 'repository link removed or retargeted',
                   finished_at = CURRENT_TIMESTAMP
             WHERE team_repository_id = :linkId
               AND trigger_kind = 'analysis'
               AND status = 'queued'
            """)
            .setParameter("linkId", linkId)
            .executeUpdate();
        entityManager.createNativeQuery("""
            UPDATE agent_sessions
               SET error = 'cancel_requested: repository link removed or retargeted'
             WHERE team_repository_id = :linkId
               AND trigger_kind = 'analysis'
               AND status IN ('starting', 'running', 'paused', 'finalizing')
               AND (error IS NULL OR error NOT LIKE 'cancel_requested:%')
            """)
            .setParameter("linkId", linkId)
            .executeUpdate();
    }

    /**
     * Derives {@code owner/repo} from a GitHub HTTPS or SSH clone URL.
     * Returns empty when the URL is not a single-repository GitHub address.
     * The slug is lowercased: GitHub repository identity is case-insensitive,
     * and the unique index compares TEXT literally.
     */
    static Optional<String> parseGithubSlug(String rawUrl) {
        if (rawUrl == null) {
            return Optional.empty();
        }
        String url = rawUrl.trim();
        Matcher https = GITHUB_HTTPS.matcher(url);
        if (https.matches()) {
            return Optional.of(normalizeSlug(https.group(1), https.group(2)));
        }
        Matcher ssh = GITHUB_SSH.matcher(url);
        if (ssh.matches()) {
            return Optional.of(normalizeSlug(ssh.group(1), ssh.group(2)));
        }
        return Optional.empty();
    }

    private static String normalizeSlug(String owner, String repo) {
        return (owner + "/" + stripGitSuffix(repo)).toLowerCase(Locale.ROOT);
    }

    private static String stripGitSuffix(String name) {
        return name.endsWith(".git") ? name.substring(0, name.length() - 4) : name;
    }

    private static String canonicalHttpsUrl(String slug) {
        return "https://github.com/" + slug + ".git";
    }

    private static String requireUrl(String repoUrl) {
        if (repoUrl == null || repoUrl.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "repo_url is required");
        }
        return repoUrl.trim();
    }

    private static String normalizeBranch(String branch) {
        if (branch == null || branch.isBlank()) {
            return "main";
        }
        String trimmed = branch.trim();
        if (trimmed.contains("..") || trimmed.indexOf(' ') >= 0 || trimmed.indexOf('\n') >= 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "branch is invalid");
        }
        return trimmed;
    }

    private static List<String> normalizePaths(List<String> paths) {
        if (paths == null || paths.isEmpty()) {
            return null;
        }
        List<String> cleaned = new ArrayList<>();
        for (String path : paths) {
            if (path == null) {
                continue;
            }
            String trimmed = path.trim().replaceAll("^/+", "").replaceAll("/+$", "");
            if (trimmed.isEmpty() || trimmed.contains("..")) {
                continue;
            }
            if (!cleaned.contains(trimmed)) {
                cleaned.add(trimmed);
            }
        }
        return cleaned.isEmpty() ? null : List.copyOf(cleaned);
    }

    private TeamRepoLink saveLink(TeamRepoLink link, String slug) {
        try {
            return repoLinkRepository.saveAndFlush(link);
        } catch (DataIntegrityViolationException e) {
            if (isTeamSlugUniqueViolation(e)) {
                throw duplicateSlug(slug);
            }
            throw e;
        }
    }

    private static boolean isTeamSlugUniqueViolation(DataIntegrityViolationException e) {
        Throwable cursor = e;
        while (cursor != null) {
            String message = cursor.getMessage();
            if (message != null && message.contains(UNIQUE_TEAM_SLUG)) {
                return true;
            }
            cursor = cursor.getCause();
        }
        return false;
    }

    private static ResponseStatusException duplicateSlug(String slug) {
        return new ResponseStatusException(HttpStatus.CONFLICT,
            "This team already links repository '" + slug + "'");
    }

    private Map<String, Object> toMap(TeamRepoLink link) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", link.getId());
        m.put("team_id", link.getTeamId());
        m.put("repo_url", link.getRepoUrl());
        m.put("repo_slug", link.getRepoSlug());
        m.put("branch", link.getBranch());
        m.put("paths", link.getPaths());
        m.put("created_at", link.getCreatedAt() != null ? link.getCreatedAt().toString() : null);
        m.put("updated_at", link.getUpdatedAt() != null ? link.getUpdatedAt().toString() : null);
        boolean hasCredentials = credentialRepository
            .findByTeamRepositoryIdAndRevokedAtIsNull(link.getId())
            .filter(c -> c.getEncryptedPrivateKey() != null && !c.getEncryptedPrivateKey().isBlank())
            .isPresent();
        m.put("has_credentials", hasCredentials);
        Optional<AiWorkflowAnalysis> latest = analysisRepository
            .findLatestSucceeded(link.getId());
        if (latest.isPresent()) {
            AiWorkflowAnalysis a = latest.get();
            Map<String, Object> summary = new LinkedHashMap<>();
            summary.put("id", a.getId());
            summary.put("status", a.getStatus());
            summary.put("source", a.getSource());
            summary.put("commit_sha", a.getCommitSha());
            summary.put("finished_at", a.getFinishedAt() != null ? a.getFinishedAt().toString() : null);
            m.put("latest_analysis", summary);
        }
        else {
            m.put("latest_analysis", null);
        }
        return m;
    }
}
