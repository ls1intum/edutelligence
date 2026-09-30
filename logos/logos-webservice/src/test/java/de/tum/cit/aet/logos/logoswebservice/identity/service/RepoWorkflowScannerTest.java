package de.tum.cit.aet.logos.logoswebservice.identity.service;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class RepoWorkflowScannerTest {

    @TempDir
    Path tempDir;

    @Test
    void scanDirectory_detectsCallSitesAndSla() throws Exception {
        Path api = tempDir.resolve("api");
        Path jobs = tempDir.resolve("jobs");
        Files.createDirectories(api);
        Files.createDirectories(jobs);

        Files.writeString(api.resolve("chat_controller.py"), """
            from fastapi import FastAPI
            from openai import OpenAI

            app = FastAPI()
            client = OpenAI()

            @app.post("/chat")
            async def chat(prompt: str):
                return client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                )
            """);

        Files.writeString(jobs.resolve("nightly_embed.py"), """
            # overnight batch job — cron: 0 2 * * *
            from openai import OpenAI

            client = OpenAI()

            def run():
                client.embeddings.create(model="text-embedding-3-small", input=["a", "b"])
            """);

        Files.writeString(tempDir.resolve("readme.md"), "no llm here\n");

        RepoWorkflowScanner scanner = new RepoWorkflowScanner();
        RepoWorkflowScanner.ScanResult result = scanner.scanDirectory(tempDir, null);

        assertThat(result.calls()).hasSizeGreaterThanOrEqualTo(2);
        assertThat(result.workflows()).extracting(RepoWorkflowScanner.WorkflowGroup::name)
            .contains("api", "jobs");

        RepoWorkflowScanner.DetectedCall syncCall = result.calls().stream()
            .filter(c -> c.filePath().startsWith("api/"))
            .findFirst()
            .orElseThrow();
        assertThat(syncCall.recommendedSla()).isEqualTo("ux-critical");
        assertThat(syncCall.detectedModel()).isEqualTo("gpt-4o-mini");
        assertThat(syncCall.justification()).isNotBlank();

        RepoWorkflowScanner.DetectedCall batchCall = result.calls().stream()
            .filter(c -> c.filePath().startsWith("jobs/"))
            .findFirst()
            .orElseThrow();
        assertThat(batchCall.recommendedSla()).isEqualTo("ux-background");

        assertThat(result.workflows().stream()
            .filter(w -> "api".equals(w.name()))
            .findFirst()
            .orElseThrow()
            .diagramMermaid()).contains("flowchart TD");
    }

    @Test
    void scanDirectory_respectsPathFilters() throws Exception {
        Path keep = tempDir.resolve("keep");
        Path skip = tempDir.resolve("skip");
        Files.createDirectories(keep);
        Files.createDirectories(skip);
        Files.writeString(keep.resolve("a.py"), "client = OpenAI()\n");
        Files.writeString(skip.resolve("b.py"), "client = Anthropic()\n");

        RepoWorkflowScanner scanner = new RepoWorkflowScanner();
        RepoWorkflowScanner.ScanResult result = scanner.scanDirectory(tempDir, List.of("keep"));

        assertThat(result.calls()).hasSize(1);
        assertThat(result.calls().getFirst().filePath()).isEqualTo("keep/a.py");
    }

    @Test
    void recommendSla_defaultsToHighPrio() {
        assertThat(RepoWorkflowScanner.recommendSla("services/worker.py\nclient = OpenAI()\n"))
            .isEqualTo("ux-high-prio");
    }
}
