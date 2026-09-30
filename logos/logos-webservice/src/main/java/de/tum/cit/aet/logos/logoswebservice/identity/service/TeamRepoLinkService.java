package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import de.tum.cit.aet.logos.logoswebservice.identity.dto.CreateTeamRepoLinkRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateTeamRepoLinkRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamRepoLink;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepoLinkRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;

@Service
public class TeamRepoLinkService {

    // https://github.com/owner/repo[.git][/...] or git@github.com:owner/repo[.git]
    private static final Pattern GITHUB_HTTPS = Pattern.compile(
        "^https?://(?:www\\.)?github\\.com/([^/\\s]+)/([^/\\s#?]+?)(?:\\.git)?/?$",
        Pattern.CASE_INSENSITIVE);
    private static final Pattern GITHUB_SSH = Pattern.compile(
        "^git@github\\.com:([^/\\s]+)/([^/\\s#?]+?)(?:\\.git)?/?$",
        Pattern.CASE_INSENSITIVE);

    private final TeamRepoLinkRepository repoLinkRepository;
    private final TeamRepository teamRepository;
    private final TeamMemberRepository teamMemberRepository;

    public TeamRepoLinkService(TeamRepoLinkRepository repoLinkRepository,
                               TeamRepository teamRepository,
                               TeamMemberRepository teamMemberRepository) {
        this.repoLinkRepository = repoLinkRepository;
        this.teamRepository = teamRepository;
        this.teamMemberRepository = teamMemberRepository;
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
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                "This team already links repository '" + slug + "'");
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
        return toMap(repoLinkRepository.save(link));
    }

    @Transactional
    public Optional<Map<String, Object>> update(int teamId, int linkId, UpdateTeamRepoLinkRequestDTO body) {
        Optional<TeamRepoLink> existing = repoLinkRepository.findByIdAndTeamId(linkId, teamId);
        if (existing.isEmpty()) {
            return Optional.empty();
        }
        TeamRepoLink link = existing.get();
        if (body.repoUrl() != null) {
            String url = requireUrl(body.repoUrl());
            String slug = parseGithubSlug(url)
                .orElseThrow(() -> new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "repo_url must be a GitHub repository URL (https://github.com/owner/repo or git@github.com:owner/repo.git)"));
            if (repoLinkRepository.existsByTeamIdAndRepoSlugAndIdNot(teamId, slug, linkId)) {
                throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "This team already links repository '" + slug + "'");
            }
            link.setRepoUrl(canonicalHttpsUrl(slug));
            link.setRepoSlug(slug);
        }
        if (body.branch() != null) {
            link.setBranch(normalizeBranch(body.branch()));
        }
        if (body.paths() != null) {
            link.setPaths(normalizePaths(body.paths()));
        }
        link.setUpdatedAt(Instant.now());
        return Optional.of(toMap(repoLinkRepository.save(link)));
    }

    @Transactional
    public boolean delete(int teamId, int linkId) {
        Optional<TeamRepoLink> existing = repoLinkRepository.findByIdAndTeamId(linkId, teamId);
        if (existing.isEmpty()) {
            return false;
        }
        repoLinkRepository.delete(existing.get());
        return true;
    }

    /**
     * Derives {@code owner/repo} from a GitHub HTTPS or SSH clone URL.
     * Returns empty when the URL is not a single-repository GitHub address.
     */
    static Optional<String> parseGithubSlug(String rawUrl) {
        if (rawUrl == null) {
            return Optional.empty();
        }
        String url = rawUrl.trim();
        Matcher https = GITHUB_HTTPS.matcher(url);
        if (https.matches()) {
            return Optional.of(https.group(1) + "/" + stripGitSuffix(https.group(2)));
        }
        Matcher ssh = GITHUB_SSH.matcher(url);
        if (ssh.matches()) {
            return Optional.of(ssh.group(1) + "/" + stripGitSuffix(ssh.group(2)));
        }
        return Optional.empty();
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
        return m;
    }
}
