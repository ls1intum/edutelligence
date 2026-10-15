package de.tum.cit.aet.logos.logoswebservice.gateway;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

import jakarta.servlet.http.HttpServletRequest;

class GatewayLoggingLevelTest {

    @ParameterizedTest
    @CsvSource({
        ", BILLING, BILLING",
        ", FULL, FULL",
        "FULL, BILLING, FULL",
        "BILLING, FULL, BILLING",
        "yes, BILLING, FULL",
        "no, FULL, BILLING",
        "YES, BILLING, FULL",
        "No, FULL, BILLING",
        "VERBOSE, FULL, BILLING",
        "'  full  ', BILLING, FULL",
    })
    void resolveHonoursHeaderPrecedence(String header, String keyLevel, String expected) {
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getHeader("logos-logging")).thenReturn(header);
        when(request.getHeader("logos_logging")).thenReturn(null);

        assertThat(GatewayLoggingLevel.resolve(request, keyLevel)).isEqualTo(expected);
    }

    @Test
    void resolveAcceptsUnderscoreHeaderSpelling() {
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getHeader("logos-logging")).thenReturn(null);
        when(request.getHeader("logos_logging")).thenReturn("yes");

        assertThat(GatewayLoggingLevel.resolve(request, "BILLING")).isEqualTo("FULL");
    }

    @Test
    void resolveTreatsNullRequestAsNoHeader() {
        assertThat(GatewayLoggingLevel.resolve(null, "FULL")).isEqualTo("FULL");
        assertThat(GatewayLoggingLevel.resolve(null, "BILLING")).isEqualTo("BILLING");
    }

    @Test
    void blankHeaderFallsBackToKey() {
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getHeader("logos-logging")).thenReturn("   ");
        when(request.getHeader("logos_logging")).thenReturn(null);

        assertThat(GatewayLoggingLevel.resolve(request, "FULL")).isEqualTo("FULL");
    }

    @Test
    void storesPayloadsOnlyForFull() {
        assertThat(GatewayLoggingLevel.storesPayloads("FULL")).isTrue();
        assertThat(GatewayLoggingLevel.storesPayloads("full")).isTrue();
        assertThat(GatewayLoggingLevel.storesPayloads("BILLING")).isFalse();
        assertThat(GatewayLoggingLevel.storesPayloads(null)).isFalse();
    }
}
