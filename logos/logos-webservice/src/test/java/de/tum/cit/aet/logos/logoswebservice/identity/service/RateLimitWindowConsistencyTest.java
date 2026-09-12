package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.lang.reflect.Field;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@code MeKeysService.RATE_LIMIT_WINDOW_SECONDS} is a copy of the window
 * the orchestrator's rate limiter enforces the rpm/tpm limits over (the
 * default of {@code RateLimitConfig.window_seconds} in the
 * logos-orchestrator's rate_limiter.py). The usage figures shown to
 * developers are only comparable to the limits if both come from the same
 * window, so this test fails when either side changes the value without the
 * other.
 */
class RateLimitWindowConsistencyTest {

    // The RateLimitConfig field definition, e.g. "window_seconds: int = 60".
    private static final Pattern WINDOW_DEFAULT = Pattern.compile("window_seconds\\s*:\\s*int\\s*=\\s*(\\d+)");

    @Test
    void windowSecondsMatchesTheOrchestratorRateLimiter() throws Exception {
        Path limiterSource = findRateLimiterSource();
        assertThat(limiterSource).exists();
        String source = Files.readString(limiterSource);
        Matcher m = WINDOW_DEFAULT.matcher(source);
        assertThat(m.find())
            .as("the RateLimitConfig.window_seconds default in rate_limiter.py")
            .isTrue();
        int orchestratorWindow = Integer.parseInt(m.group(1));

        Field field = MeKeysService.class.getDeclaredField("RATE_LIMIT_WINDOW_SECONDS");
        field.setAccessible(true);
        int webserviceWindow = field.getInt(null);

        assertThat(webserviceWindow)
            .as("MeKeysService.RATE_LIMIT_WINDOW_SECONDS must match the orchestrator rate limiter window "
                + "(update both together; the comment in rate_limiter.py points at this constant)")
            .isEqualTo(orchestratorWindow);
    }

    // Maven (and CI) run the tests with the webservice module directory as
    // the working directory; walk up to the checkout root so the test also
    // works when run from the repository root.
    private static Path findRateLimiterSource() {
        Path relative = Path.of("logos", "logos-orchestrator", "src", "logos", "rate_limiter.py");
        for (Path dir = Path.of(System.getProperty("user.dir")).toAbsolutePath();
             dir != null;
             dir = dir.getParent()) {
            Path candidate = dir.resolve(relative);
            if (Files.exists(candidate)) {
                return candidate;
            }
        }
        return Path.of("rate_limiter.py");
    }
}
