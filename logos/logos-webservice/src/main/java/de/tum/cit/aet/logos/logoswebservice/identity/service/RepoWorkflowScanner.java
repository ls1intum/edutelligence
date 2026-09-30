package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.Charset;
import java.nio.charset.MalformedInputException;
import java.nio.charset.StandardCharsets;
import java.nio.file.FileVisitResult;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.attribute.BasicFileAttributes;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

/**
 * Heuristic scan of a GitHub repository for LLM call sites and coarse SLA
 * recommendations. Public repos are fetched as a zipball; tests use
 * {@link #scanDirectory(Path, List)}.
 */
@Service
public class RepoWorkflowScanner {

    private static final Set<String> TEXT_EXTENSIONS = Set.of(
        ".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".kt", ".go", ".rs",
        ".rb", ".php", ".cs", ".swift", ".scala", ".m", ".mm", ".vue", ".svelte",
        ".yml", ".yaml", ".toml", ".json", ".md", ".txt", ".sh", ".bash");

    private static final Set<String> SKIP_DIR_NAMES = Set.of(
        ".git", "node_modules", "dist", "build", "target", ".venv", "venv",
        "__pycache__", ".idea", ".next", "vendor", "coverage");

    private static final Pattern CALL_SITE = Pattern.compile(
        "(?:"
            + "OpenAI\\s*\\(|AsyncOpenAI\\s*\\(|openai\\.OpenAI\\s*\\("
            + "|openai\\.chat\\.completions\\.create\\s*\\("
            + "|ChatCompletion\\.create\\s*\\("
            + "|Anthropic\\s*\\(|AsyncAnthropic\\s*\\(|anthropic\\.Anthropic\\s*\\("
            + "|anthropic\\.messages\\.create\\s*\\("
            + "|client\\.chat\\.completions\\.create\\s*\\("
            + "|client\\.messages\\.create\\s*\\("
            + "|embeddings\\.create\\s*\\(|\\.embeddings\\.create\\s*\\("
            + "|audio\\.transcriptions\\.create\\s*\\(|whisper"
            + "|batches\\.create\\s*\\(|Batch\\s*\\("
            + "|LogosClient\\s*\\(|logos_client|from\\s+logos\\s+import"
            + "|base_url\\s*=\\s*[\"'][^\"']*logos"
            + ")",
        Pattern.CASE_INSENSITIVE);

    private static final Pattern MODEL_GUESS = Pattern.compile(
        "(?:model|model_name|deployment)\\s*[=:]\\s*[\"']([^\"']+)[\"']",
        Pattern.CASE_INSENSITIVE);

    private static final Pattern UX_CRITICAL = Pattern.compile(
        "(?i)@(?:RestController|Controller|GetMapping|PostMapping|RequestMapping)"
            + "|HttpServlet|FastAPI|@app\\.(?:get|post|put|delete|patch)"
            + "|express\\.(?:get|post)|flask\\.route|await\\s+"
            + "|ResponseEntity|HttpResponse|sync\\s+def\\s+");

    private static final Pattern UX_BACKGROUND = Pattern.compile(
        "(?i)@Scheduled|cron|celery|overnight|batch[_-]?job|APScheduler"
            + "|schedule\\.every|BackgroundTask|@async_to_sync"
            + "|nightly|off[-_]?peak|queue\\.delay|apply_async");

    private static final Pattern COMMIT_SHA = Pattern.compile("^[0-9a-f]{7,40}$");

    private final HttpClient httpClient;

    public RepoWorkflowScanner() {
        this(HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(20)).build());
    }

    RepoWorkflowScanner(HttpClient httpClient) {
        this.httpClient = httpClient;
    }

    public ScanResult scanPublicGithub(String repoSlug, String branch, List<String> pathFilters) {
        if (repoSlug == null || repoSlug.isBlank() || !repoSlug.contains("/")) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "repo_slug is invalid");
        }
        String safeBranch = (branch == null || branch.isBlank()) ? "main" : branch.trim();
        String url = "https://codeload.github.com/" + repoSlug.trim()
            + "/zip/refs/heads/" + safeBranch;
        Path tempRoot = null;
        try {
            tempRoot = Files.createTempDirectory("logos-repo-scan-");
            Path zipPath = tempRoot.resolve("repo.zip");
            download(url, zipPath);
            Path extracted = tempRoot.resolve("extracted");
            Files.createDirectories(extracted);
            unzip(zipPath, extracted);
            Path contentRoot = firstChildDir(extracted);
            if (contentRoot == null) {
                contentRoot = extracted;
            }
            String commitSha = guessCommitSha(contentRoot.getFileName().toString());
            ScanResult scanned = scanDirectory(contentRoot, pathFilters);
            return new ScanResult(commitSha, scanned.workflows(), scanned.calls());
        }
        catch (ResponseStatusException e) {
            throw e;
        }
        catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                "Interrupted while downloading repository zipball");
        }
        catch (IOException e) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                "Failed to download or unpack repository: " + e.getMessage());
        }
        finally {
            if (tempRoot != null) {
                deleteRecursivelyQuietly(tempRoot);
            }
        }
    }

    /**
     * Package-visible entry used by unit tests with an on-disk fixture.
     * {@code root} is the repository content root (not the zip wrapper).
     */
    ScanResult scanDirectory(Path root, List<String> pathFilters) throws IOException {
        List<DetectedCall> calls = new ArrayList<>();
        List<Path> files = listTextFiles(root, pathFilters);
        for (Path file : files) {
            String relative = root.relativize(file).toString().replace('\\', '/');
            String content;
            try {
                content = Files.readString(file, StandardCharsets.UTF_8);
            }
            catch (MalformedInputException e) {
                try {
                    content = Files.readString(file, Charset.forName("ISO-8859-1"));
                }
                catch (IOException ignored) {
                    continue;
                }
            }
            String[] lines = content.split("\\R", -1);
            Matcher matcher = CALL_SITE.matcher(content);
            while (matcher.find()) {
                int startOffset = matcher.start();
                int line = lineNumberAt(content, startOffset);
                int endLine = lineNumberAt(content, matcher.end() - 1);
                String window = contextWindow(lines, line - 1, 12);
                String pathAndWindow = relative + "\n" + window;
                String sla = recommendSla(pathAndWindow);
                String model = guessModel(window);
                float confidence = slaConfidence(sla, pathAndWindow);
                String kind = classifyCallKind(matcher.group());
                String justification = buildJustification(sla, kind, relative);
                calls.add(new DetectedCall(
                    relative, line, Math.max(line, endLine), model, sla, confidence, justification));
            }
        }

        Map<String, List<DetectedCall>> groups = new LinkedHashMap<>();
        for (DetectedCall call : calls) {
            groups.computeIfAbsent(workflowGroup(call.filePath()), k -> new ArrayList<>()).add(call);
        }

        List<WorkflowGroup> workflows = new ArrayList<>();
        int order = 0;
        for (Map.Entry<String, List<DetectedCall>> entry : groups.entrySet()) {
            String name = entry.getKey();
            List<DetectedCall> groupCalls = entry.getValue();
            String trigger = summarizeTrigger(groupCalls);
            String mermaid = buildMermaid(name, groupCalls);
            workflows.add(new WorkflowGroup(name, trigger, mermaid, order++));
        }
        if (workflows.isEmpty()) {
            workflows.add(new WorkflowGroup(
                "repository",
                "no LLM call sites detected",
                "flowchart TD\n  A[Scan complete] --> B[No LLM clients found]\n",
                0));
        }
        return new ScanResult("unknown", workflows, calls);
    }

    private void download(String url, Path dest) throws IOException, InterruptedException {
        HttpRequest request = HttpRequest.newBuilder(URI.create(url))
            .timeout(Duration.ofMinutes(2))
            .header("User-Agent", "logos-webservice-repo-scanner")
            .GET()
            .build();
        HttpResponse<InputStream> response = httpClient.send(request, HttpResponse.BodyHandlers.ofInputStream());
        if (response.statusCode() == 404) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND,
                "Repository or branch not found (public zipball 404)");
        }
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                "GitHub zipball download failed with HTTP " + response.statusCode());
        }
        try (InputStream in = response.body()) {
            Files.copy(in, dest);
        }
    }

    private static void unzip(Path zipPath, Path destDir) throws IOException {
        try (ZipInputStream zis = new ZipInputStream(Files.newInputStream(zipPath))) {
            ZipEntry entry;
            while ((entry = zis.getNextEntry()) != null) {
                Path out = destDir.resolve(entry.getName()).normalize();
                if (!out.startsWith(destDir)) {
                    throw new IOException("Zip entry escapes destination: " + entry.getName());
                }
                if (entry.isDirectory()) {
                    Files.createDirectories(out);
                }
                else {
                    Files.createDirectories(out.getParent());
                    Files.copy(zis, out);
                }
            }
        }
    }

    private static Path firstChildDir(Path extracted) throws IOException {
        try (var stream = Files.list(extracted)) {
            return stream.filter(Files::isDirectory).sorted().findFirst().orElse(null);
        }
    }

    static String guessCommitSha(String rootFolderName) {
        if (rootFolderName == null || rootFolderName.isBlank()) {
            return "unknown";
        }
        int dash = rootFolderName.lastIndexOf('-');
        if (dash < 0 || dash == rootFolderName.length() - 1) {
            return "unknown";
        }
        String suffix = rootFolderName.substring(dash + 1).toLowerCase(Locale.ROOT);
        if (COMMIT_SHA.matcher(suffix).matches()) {
            return suffix;
        }
        return "unknown";
    }

    private static List<Path> listTextFiles(Path root, List<String> pathFilters) throws IOException {
        List<Path> files = new ArrayList<>();
        List<String> filters = normalizeFilters(pathFilters);
        Files.walkFileTree(root, new SimpleFileVisitor<>() {
            @Override
            public FileVisitResult preVisitDirectory(Path dir, BasicFileAttributes attrs) {
                if (dir.equals(root)) {
                    return FileVisitResult.CONTINUE;
                }
                String name = dir.getFileName().toString();
                if (SKIP_DIR_NAMES.contains(name) || name.startsWith(".")) {
                    return FileVisitResult.SKIP_SUBTREE;
                }
                return FileVisitResult.CONTINUE;
            }

            @Override
            public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) {
                if (!attrs.isRegularFile() || attrs.size() > 1_000_000) {
                    return FileVisitResult.CONTINUE;
                }
                String relative = root.relativize(file).toString().replace('\\', '/');
                if (!matchesFilters(relative, filters)) {
                    return FileVisitResult.CONTINUE;
                }
                String lower = relative.toLowerCase(Locale.ROOT);
                int dot = lower.lastIndexOf('.');
                if (dot < 0 || !TEXT_EXTENSIONS.contains(lower.substring(dot))) {
                    return FileVisitResult.CONTINUE;
                }
                files.add(file);
                return FileVisitResult.CONTINUE;
            }
        });
        files.sort(Comparator.comparing(p -> root.relativize(p).toString()));
        return files;
    }

    private static List<String> normalizeFilters(List<String> pathFilters) {
        if (pathFilters == null || pathFilters.isEmpty()) {
            return List.of();
        }
        return pathFilters.stream()
            .filter(p -> p != null && !p.isBlank())
            .map(p -> p.trim().replaceAll("^/+", "").replaceAll("/+$", ""))
            .filter(p -> !p.isEmpty())
            .toList();
    }

    private static boolean matchesFilters(String relative, List<String> filters) {
        if (filters.isEmpty()) {
            return true;
        }
        for (String filter : filters) {
            if (relative.equals(filter) || relative.startsWith(filter + "/")) {
                return true;
            }
        }
        return false;
    }

    private static int lineNumberAt(String content, int offset) {
        int line = 1;
        int end = Math.min(offset, content.length());
        for (int i = 0; i < end; i++) {
            if (content.charAt(i) == '\n') {
                line++;
            }
        }
        return line;
    }

    private static String contextWindow(String[] lines, int centerZeroBased, int radius) {
        int from = Math.max(0, centerZeroBased - radius);
        int to = Math.min(lines.length - 1, centerZeroBased + radius);
        StringBuilder sb = new StringBuilder();
        for (int i = from; i <= to; i++) {
            if (i > from) {
                sb.append('\n');
            }
            sb.append(lines[i]);
        }
        return sb.toString();
    }

    static String recommendSla(String pathAndWindow) {
        if (UX_BACKGROUND.matcher(pathAndWindow).find()) {
            return "ux-background";
        }
        if (UX_CRITICAL.matcher(pathAndWindow).find()) {
            return "ux-critical";
        }
        String lower = pathAndWindow.toLowerCase(Locale.ROOT);
        if (lower.contains("/cron/") || lower.contains("/batch/") || lower.contains("/jobs/")) {
            return "ux-background";
        }
        if (lower.contains("/controller/") || lower.contains("/api/") || lower.contains("/routes/")) {
            return "ux-critical";
        }
        return "ux-high-prio";
    }

    private static float slaConfidence(String sla, String pathAndWindow) {
        return switch (sla) {
            case "ux-critical" -> UX_CRITICAL.matcher(pathAndWindow).find() ? 0.75f : 0.55f;
            case "ux-background" -> UX_BACKGROUND.matcher(pathAndWindow).find() ? 0.8f : 0.6f;
            default -> 0.5f;
        };
    }

    private static String guessModel(String window) {
        Matcher m = MODEL_GUESS.matcher(window);
        if (m.find()) {
            return m.group(1);
        }
        return null;
    }

    private static String classifyCallKind(String matched) {
        String lower = matched.toLowerCase(Locale.ROOT);
        if (lower.contains("embedding")) {
            return "embeddings";
        }
        if (lower.contains("transcription") || lower.contains("whisper")) {
            return "transcription";
        }
        if (lower.contains("batch")) {
            return "batch";
        }
        if (lower.contains("anthropic")) {
            return "anthropic";
        }
        if (lower.contains("logos")) {
            return "logos";
        }
        return "openai-compatible";
    }

    private static String buildJustification(String sla, String kind, String file) {
        return switch (sla) {
            case "ux-critical" ->
                "Detected " + kind + " call in interactive path '" + file + "' (HTTP/controller/await patterns).";
            case "ux-background" ->
                "Detected " + kind + " call near cron/batch/scheduled patterns in '" + file + "'.";
            default ->
                "Detected " + kind + " call in '" + file + "' without a clear sync or overnight signal.";
        };
    }

    private static String workflowGroup(String filePath) {
        int slash = filePath.indexOf('/');
        if (slash <= 0) {
            return filePath;
        }
        return filePath.substring(0, slash);
    }

    private static String summarizeTrigger(List<DetectedCall> calls) {
        boolean critical = calls.stream().anyMatch(c -> "ux-critical".equals(c.recommendedSla()));
        boolean background = calls.stream().anyMatch(c -> "ux-background".equals(c.recommendedSla()));
        if (critical && background) {
            return "mixed interactive and scheduled LLM usage";
        }
        if (critical) {
            return "interactive / HTTP-triggered LLM usage";
        }
        if (background) {
            return "scheduled / batch LLM usage";
        }
        return "asynchronous LLM usage";
    }

    private static String buildMermaid(String name, List<DetectedCall> calls) {
        StringBuilder sb = new StringBuilder();
        sb.append("flowchart TD\n");
        String startId = "start_" + sanitizeId(name);
        sb.append("  ").append(startId).append("[\"").append(escapeMermaid(name)).append("\"]\n");
        int i = 0;
        for (DetectedCall call : calls.stream().limit(12).toList()) {
            String nodeId = "c" + sanitizeId(name) + "_" + (i++);
            String label = call.filePath() + ":" + call.startLine()
                + " (" + call.recommendedSla() + ")";
            sb.append("  ").append(nodeId).append("[\"").append(escapeMermaid(label)).append("\"]\n");
            sb.append("  ").append(startId).append(" --> ").append(nodeId).append('\n');
        }
        if (calls.size() > 12) {
            sb.append("  more_").append(sanitizeId(name))
                .append("[\"").append(calls.size() - 12).append(" more call sites\"]\n");
            sb.append("  ").append(startId).append(" --> more_").append(sanitizeId(name)).append('\n');
        }
        return sb.toString();
    }

    private static String sanitizeId(String raw) {
        return raw.replaceAll("[^A-Za-z0-9_]", "_");
    }

    private static String escapeMermaid(String raw) {
        return raw.replace("\"", "'").replace("\n", " ");
    }

    private static void deleteRecursivelyQuietly(Path root) {
        try {
            if (!Files.exists(root)) {
                return;
            }
            Files.walkFileTree(root, new SimpleFileVisitor<>() {
                @Override
                public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) throws IOException {
                    Files.deleteIfExists(file);
                    return FileVisitResult.CONTINUE;
                }

                @Override
                public FileVisitResult postVisitDirectory(Path dir, IOException exc) throws IOException {
                    Files.deleteIfExists(dir);
                    return FileVisitResult.CONTINUE;
                }
            });
        }
        catch (IOException ignored) {
            // best-effort cleanup
        }
    }

    public record ScanResult(String commitSha, List<WorkflowGroup> workflows, List<DetectedCall> calls) {
        public ScanResult {
            workflows = List.copyOf(workflows);
            calls = List.copyOf(calls);
        }

        @Override
        public String toString() {
            return "ScanResult{commitSha=" + commitSha
                + ", workflows=" + workflows.stream().map(WorkflowGroup::name).collect(Collectors.joining(","))
                + ", calls=" + calls.size() + "}";
        }
    }

    public record WorkflowGroup(String name, String triggerSummary, String diagramMermaid, int sortOrder) {}

    public record DetectedCall(
        String filePath,
        int startLine,
        int endLine,
        String detectedModel,
        String recommendedSla,
        float confidence,
        String justification
    ) {}
}
