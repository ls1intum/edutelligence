package de.tum.cit.aet.logos.logoswebservice;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.junit.jupiter.api.Test;

class LiquibaseChangelogOrderTest {

    private static final Pattern CHANGELOG_INCLUDE =
        Pattern.compile("file=\"liquibase/changelog/(\\d{3})_[^\"]+\\.xml\"");

    @Test
    void changelogIncludesAreStrictlyIncreasing() throws IOException {
        try (InputStream stream = getClass().getResourceAsStream("/liquibase/changelog/master.xml")) {
            assertThat(stream).as("Liquibase master changelog").isNotNull();
            String master = new String(stream.readAllBytes(), StandardCharsets.UTF_8);
            Matcher includes = CHANGELOG_INCLUDE.matcher(master);
            int previous = -1;

            while (includes.find()) {
                int current = Integer.parseInt(includes.group(1));
                assertThat(current)
                    .as("changelog number after %03d", previous)
                    .isGreaterThan(previous);
                previous = current;
            }

            assertThat(previous).as("at least one numbered changelog include").isGreaterThanOrEqualTo(0);
        }
    }
}
