package de.tum.cit.aet.logos.logoswebservice.gateway;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.atomic.AtomicBoolean;

import org.junit.jupiter.api.Test;

class GatewayUpstreamPumpTest {

    @Test
    void aRelayThatStartsLate_keepsTheUpstreamTimestamps() throws Exception {
        Instant headersAt = Instant.now();
        GatewayCloudForwarder.UpstreamPump pump = GatewayCloudForwarder.UpstreamPump.start(
            new ByteArrayInputStream("data: hi\n\n".getBytes(StandardCharsets.UTF_8)), headersAt,
            Duration.ofMinutes(1));
        // The relay waits for an executor thread while the upstream finishes.
        Thread.sleep(500);
        Instant relayStarted = Instant.now();

        ByteArrayOutputStream out = new ByteArrayOutputStream();
        try (pump) {
            pump.transferTo(out);
        }

        assertThat(out.toString(StandardCharsets.UTF_8)).isEqualTo("data: hi\n\n");
        assertThat(pump.endedAt()).isBefore(relayStarted.minusMillis(300));
        assertThat(pump.currentChunkAt()).isBefore(relayStarted.minusMillis(300));
    }

    @Test
    void aRelayThatNeverStarts_releasesTheUpstream() throws Exception {
        AtomicBoolean closed = new AtomicBoolean();
        InputStream endless = new InputStream() {
            @Override
            public int read() {
                return 'x';
            }

            @Override
            public int read(byte[] b, int off, int len) throws IOException {
                if (closed.get()) {
                    throw new IOException("closed");
                }
                java.util.Arrays.fill(b, off, off + len, (byte) 'x');
                return len;
            }

            @Override
            public void close() {
                closed.set(true);
            }
        };
        GatewayCloudForwarder.UpstreamPump pump = GatewayCloudForwarder.UpstreamPump.start(
            endless, Instant.now(), Duration.ofMillis(100));

        long deadline = System.nanoTime() + Duration.ofSeconds(10).toNanos();
        while (!closed.get() && System.nanoTime() < deadline) {
            Thread.sleep(50);
        }

        assertThat(closed).isTrue();
        assertThatThrownBy(() -> pump.transferTo(new ByteArrayOutputStream())).isInstanceOf(IOException.class);
    }
}
