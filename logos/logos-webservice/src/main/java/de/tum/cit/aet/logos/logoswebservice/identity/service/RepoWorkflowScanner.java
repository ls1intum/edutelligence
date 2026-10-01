package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
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
import java.nio.file.attribute.PosixFilePermission;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.EnumSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.identity.ObjectivePriority;

/**
 * Heuristic scan of a GitHub repository for LLM call sites and coarse SLA
 * recommendations. Public repos are fetched as a commit-pinned zipball; private
 * repos use a per-link deploy-key PEM via {@code git} over SSH. Tests use
 * {@link #scanDirectory(Path, List)}.
 */
@Service
public class RepoWorkflowScanner {

    static final long MAX_DOWNLOAD_BYTES = 80L * 1024 * 1024;
    static final long MAX_EXTRACTED_BYTES = 200L * 1024 * 1024;
    static final int MAX_ZIP_ENTRIES = 50_000;
    /** Cap recommendation work from dense synthetic sources. */
    static final int MAX_DETECTED_CALLS = 500;

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

    private final HttpClient httpClient;
    private final ObjectMapper objectMapper;

    public RepoWorkflowScanner() {
        this(HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(20)).build(),
            new ObjectMapper());
    }

    RepoWorkflowScanner(HttpClient httpClient) {
        this(httpClient, new ObjectMapper());
    }

    RepoWorkflowScanner(HttpClient httpClient, ObjectMapper objectMapper) {
        this.httpClient = httpClient;
        this.objectMapper = objectMapper;
    }

    /** Public zipball scan (no deploy key). */
    public ScanResult scanPublicGithub(String repoSlug, String branch, List<String> pathFilters) {
        return scanGithub(repoSlug, branch, pathFilters, null);
    }

    /**
     * Scan a GitHub repository. When {@code deployKeyPem} is non-null, clones
     * over SSH with that key; otherwise resolves the branch to a commit SHA and
     * downloads the public zipball pinned to that SHA.
     */
    public ScanResult scanGithub(String repoSlug, String branch, List<String> pathFilters,
                                 String deployKeyPem) {
        if (repoSlug == null || repoSlug.isBlank() || !repoSlug.contains("/")) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "repo_slug is invalid");
        }
        String safeBranch = (branch == null || branch.isBlank()) ? "main" : branch.trim();
        Path tempRoot = null;
        try {
            tempRoot = Files.createTempDirectory("logos-repo-scan-");
            if (deployKeyPem != null && !deployKeyPem.isBlank()) {
                return scanViaDeployKey(tempRoot, repoSlug.trim(), safeBranch, pathFilters, deployKeyPem);
            }
            String commitSha = resolveCommitSha(repoSlug.trim(), safeBranch);
            Path zipPath = tempRoot.resolve("repo.zip");
            String url = "https://codeload.github.com/" + repoSlug.trim() + "/zip/" + commitSha;
            downloadBounded(url, zipPath);
            Path extracted = tempRoot.resolve("extracted");
            Files.createDirectories(extracted);
            unzipBounded(zipPath, extracted);
            Path contentRoot = firstChildDir(extracted);
            if (contentRoot == null) {
                contentRoot = extracted;
            }
            ScanResult scanned = scanDirectory(contentRoot, pathFilters);
            return new ScanResult(commitSha, scanned.workflows(), scanned.calls());
        }
        catch (ResponseStatusException e) {
            throw e;
        }
        catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                "Interrupted while downloading repository");
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

    private ScanResult scanViaDeployKey(Path tempRoot, String repoSlug, String branch,
                                        List<String> pathFilters, String deployKeyPem)
        throws IOException, InterruptedException {
        Path keyFile = tempRoot.resolve("deploy_key");
        Files.writeString(keyFile, deployKeyPem.endsWith("\n") ? deployKeyPem : deployKeyPem + "\n");
        try {
            Files.setPosixFilePermissions(keyFile, EnumSet.of(
                PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE));
        }
        catch (UnsupportedOperationException ignored) {
            // non-POSIX temp FS (e.g. some CI runners)
        }
        Path cloneDir = tempRoot.resolve("clone");
        String sshCmd = "ssh -i " + keyFile.toAbsolutePath()
            + " -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null";
        String sshUrl = "git@github.com:" + repoSlug + ".git";
        runGitBounded(tempRoot, cloneDir, sshCmd, "clone", "--depth", "1", "--branch", branch, sshUrl,
            cloneDir.toAbsolutePath().toString());
        enforceDirSizeLimit(cloneDir);
        String commitSha = runGitCapture(cloneDir, sshCmd, "rev-parse", "HEAD").trim();
        ScanResult scanned = scanDirectory(cloneDir, pathFilters);
        return new ScanResult(commitSha, scanned.workflows(), scanned.calls());
    }

    private String resolveCommitSha(String repoSlug, String branch)
        throws IOException, InterruptedException {
        String url = "https://api.github.com/repos/" + repoSlug + "/commits/"
            + java.net.URLEncoder.encode(branch, StandardCharsets.UTF_8).replace("+", "%20");
        HttpRequest request = HttpRequest.newBuilder(URI.create(url))
            .timeout(Duration.ofSeconds(30))
            .header("User-Agent", "logos-webservice-repo-scanner")
            .header("Accept", "application/vnd.github+json")
            .GET()
            .build();
        HttpResponse<InputStream> response = httpClient.send(
            request, HttpResponse.BodyHandlers.ofInputStream());
        try (InputStream body = response.body()) {
            if (response.statusCode() == 404) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND,
                    "Repository or branch not found");
            }
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                    "GitHub commit lookup failed with HTTP " + response.statusCode());
            }
            JsonNode root = objectMapper.readTree(body);
            String sha = root.path("sha").asText(null);
            if (sha == null || sha.isBlank()) {
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                    "GitHub commit lookup returned no sha");
            }
            return sha;
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
            int line = 1;
            int scanPos = 0;
            while (matcher.find()) {
                if (calls.size() >= MAX_DETECTED_CALLS) {
                    break;
                }
                int startOffset = matcher.start();
                while (scanPos < startOffset) {
                    if (content.charAt(scanPos) == '\n') {
                        line++;
                    }
                    scanPos++;
                }
                int endLine = line;
                for (int i = startOffset; i < matcher.end(); i++) {
                    if (content.charAt(i) == '\n') {
                        endLine++;
                    }
                }
                String window = contextWindow(lines, line - 1, 12);
                String pathAndWindow = relative + "\n" + window;
                String sla = recommendSla(pathAndWindow);
                String model = guessModel(window);
                float confidence = slaConfidence(sla, pathAndWindow);
                String kind = classifyCallKind(matcher.group());
                String justification = buildJustification(sla, kind, relative);
                calls.add(new DetectedCall(
                    relative, line, Math.max(line, endLine), model, sla,
                    ObjectivePriority.forSla(sla), confidence, justification));
            }
            if (calls.size() >= MAX_DETECTED_CALLS) {
                break;
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

    private void downloadBounded(String url, Path dest) throws IOException, InterruptedException {
        HttpRequest request = HttpRequest.newBuilder(URI.create(url))
            .timeout(Duration.ofMinutes(2))
            .header("User-Agent", "logos-webservice-repo-scanner")
            .GET()
            .build();
        HttpResponse<InputStream> response = httpClient.send(
            request, HttpResponse.BodyHandlers.ofInputStream());
        try (InputStream in = response.body()) {
            if (response.statusCode() == 404) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND,
                    "Repository or commit not found (zipball 404)");
            }
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                    "GitHub zipball download failed with HTTP " + response.statusCode());
            }
            long copied = 0;
            byte[] buf = new byte[64 * 1024];
            try (OutputStream out = Files.newOutputStream(dest)) {
                int n;
                while ((n = in.read(buf)) >= 0) {
                    copied += n;
                    if (copied > MAX_DOWNLOAD_BYTES) {
                        throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE,
                            "Repository archive exceeds " + MAX_DOWNLOAD_BYTES + " bytes");
                    }
                    out.write(buf, 0, n);
                }
            }
        }
    }

    static void unzipBounded(Path zipPath, Path destDir) throws IOException {
        long extracted = 0;
        int entries = 0;
        try (ZipInputStream zis = new ZipInputStream(Files.newInputStream(zipPath))) {
            ZipEntry entry;
            while ((entry = zis.getNextEntry()) != null) {
                entries++;
                if (entries > MAX_ZIP_ENTRIES) {
                    throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE,
                        "Repository archive has too many entries");
                }
                Path out = destDir.resolve(entry.getName()).normalize();
                if (!out.startsWith(destDir)) {
                    throw new IOException("Zip entry escapes destination: " + entry.getName());
                }
                if (entry.isDirectory()) {
                    Files.createDirectories(out);
                }
                else {
                    Files.createDirectories(out.getParent());
                    long declared = entry.getSize();
                    if (declared > 0 && extracted + declared > MAX_EXTRACTED_BYTES) {
                        throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE,
                            "Extracted repository exceeds size limit");
                    }
                    try (OutputStream os = Files.newOutputStream(out)) {
                        byte[] buf = new byte[64 * 1024];
                        int n;
                        while ((n = zis.read(buf)) >= 0) {
                            extracted += n;
                            if (extracted > MAX_EXTRACTED_BYTES) {
                                throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE,
                                    "Extracted repository exceeds size limit");
                            }
                            os.write(buf, 0, n);
                        }
                    }
                }
            }
        }
    }

    private static Path firstChildDir(Path extracted) throws IOException {
        try (var stream = Files.list(extracted)) {
            return stream.filter(Files::isDirectory).sorted().findFirst().orElse(null);
        }
    }

    /** Clone under a live directory-size watch so private checkouts share the extract budget. */
    private static void runGitBounded(Path cwd, Path watchDir, String sshCmd, String... args)
        throws IOException, InterruptedException {
        List<String> cmd = new ArrayList<>();
        cmd.add("git");
        cmd.addAll(List.of(args));
        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.directory(cwd.toFile());
        pb.redirectErrorStream(true);
        Map<String, String> env = pb.environment();
        env.put("GIT_SSH_COMMAND", sshCmd);
        env.put("GIT_TERMINAL_PROMPT", "0");
        Process p = pb.start();
        java.util.concurrent.atomic.AtomicBoolean overflow =
            new java.util.concurrent.atomic.AtomicBoolean(false);
        Thread watcher = Thread.ofVirtual().start(() -> {
            try {
                while (!Thread.currentThread().isInterrupted() && p.isAlive()) {
                    if (Files.exists(watchDir) && directorySize(watchDir) > MAX_EXTRACTED_BYTES) {
                        overflow.set(true);
                        p.destroyForcibly();
                        return;
                    }
                    Thread.sleep(250);
                }
            }
            catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
            catch (IOException ignored) {
                // main path surfaces git failures
            }
        });
        StringBuilder output = new StringBuilder();
        Thread reader = Thread.ofVirtual().start(() -> {
            try (InputStream in = p.getInputStream()) {
                byte[] buf = new byte[8 * 1024];
                int n;
                long total = 0;
                while ((n = in.read(buf)) >= 0) {
                    total += n;
                    if (total <= 1_000_000) {
                        output.append(new String(buf, 0, n, StandardCharsets.UTF_8));
                    }
                }
            }
            catch (IOException ignored) {
                // process ended
            }
        });
        try {
            if (!p.waitFor(3, TimeUnit.MINUTES)) {
                p.destroyForcibly();
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "git timed out");
            }
        }
        catch (InterruptedException e) {
            p.destroyForcibly();
            Thread.currentThread().interrupt();
            throw e;
        }
        finally {
            watcher.interrupt();
            reader.interrupt();
            try {
                watcher.join(1000);
                reader.join(1000);
            }
            catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
        if (overflow.get()) {
            throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE,
                "Cloned repository exceeds size limit");
        }
        if (p.exitValue() != 0) {
            String msg = output.toString().strip();
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                "git failed: " + (msg.isEmpty() ? "exit " + p.exitValue()
                    : msg.lines().findFirst().orElse(msg)));
        }
        enforceDirSizeLimit(watchDir);
    }

    private static void enforceDirSizeLimit(Path dir) throws IOException {
        if (Files.exists(dir) && directorySize(dir) > MAX_EXTRACTED_BYTES) {
            throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE,
                "Cloned repository exceeds size limit");
        }
    }

    private static long directorySize(Path root) throws IOException {
        final long[] total = {0L};
        Files.walkFileTree(root, new SimpleFileVisitor<>() {
            @Override
            public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) {
                total[0] += attrs.size();
                return FileVisitResult.CONTINUE;
            }
        });
        return total[0];
    }

    private static String runGitCapture(Path cwd, String sshCmd, String... args)
        throws IOException, InterruptedException {
        List<String> cmd = new ArrayList<>();
        cmd.add("git");
        cmd.addAll(List.of(args));
        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.directory(cwd.toFile());
        pb.redirectErrorStream(true);
        Map<String, String> env = pb.environment();
        env.put("GIT_SSH_COMMAND", sshCmd);
        env.put("GIT_TERMINAL_PROMPT", "0");
        Process p = pb.start();
        StringBuilder output = new StringBuilder();
        Thread reader = Thread.ofVirtual().start(() -> {
            try (InputStream in = p.getInputStream()) {
                byte[] buf = new byte[8 * 1024];
                int n;
                long total = 0;
                while ((n = in.read(buf)) >= 0) {
                    total += n;
                    if (total <= 1_000_000) {
                        output.append(new String(buf, 0, n, StandardCharsets.UTF_8));
                    }
                }
            }
            catch (IOException ignored) {
                // process ended
            }
        });
        try {
            if (!p.waitFor(3, TimeUnit.MINUTES)) {
                p.destroyForcibly();
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "git timed out");
            }
        }
        catch (InterruptedException e) {
            p.destroyForcibly();
            Thread.currentThread().interrupt();
            throw e;
        }
        finally {
            reader.interrupt();
            try {
                reader.join(1000);
            }
            catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
        if (p.exitValue() != 0) {
            String msg = output.toString().strip();
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                "git failed: " + (msg.isEmpty() ? "exit " + p.exitValue()
                    : msg.lines().findFirst().orElse(msg)));
        }
        return output.toString();
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
        java.util.List<String> objectivePriority,
        float confidence,
        String justification
    ) {}
}
