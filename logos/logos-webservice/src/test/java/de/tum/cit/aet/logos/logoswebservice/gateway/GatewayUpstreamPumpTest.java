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

    /** Sends one small event, then stalls in read() until it is closed. */
    private static final class StallingUpstream extends InputStream {
        final java.util.concurrent.CountDownLatch closed = new java.util.concurrent.CountDownLatch(1);
        private boolean sent;

        @Override
        public int read() throws IOException {
            byte[] one = new byte[1];
            return read(one, 0, 1) == -1 ? -1 : one[0];
        }

        @Override
        public int read(byte[] b, int off, int len) throws IOException {
            if (!sent) {
                sent = true;
                b[off] = 'x';
                return 1;
            }
            try {
                closed.await();
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
            throw new IOException("closed");
        }

        @Override
        public void close() {
            closed.countDown();
        }
    }

    @Test
    void aRelayThatNeverStarts_releasesAStalledUpstreamAfterTheAttachTimeout() throws Exception {
        StallingUpstream upstream = new StallingUpstream();
        GatewayCloudForwarder.UpstreamPump pump = GatewayCloudForwarder.UpstreamPump.start(
            upstream, Instant.now(), Duration.ofMillis(200));

        assertThat(upstream.closed.await(5, java.util.concurrent.TimeUnit.SECONDS)).isTrue();
        assertThat(pump.isClosed()).isTrue();
        assertThatThrownBy(() -> pump.transferTo(new ByteArrayOutputStream())).isInstanceOf(IOException.class);
    }

    @Test
    void theEndOfTheRequest_releasesTheUpstreamOfARelayThatNeverRan() throws Exception {
        StallingUpstream upstream = new StallingUpstream();
        GatewayCloudForwarder.UpstreamPump pump = GatewayCloudForwarder.UpstreamPump.start(
            upstream, Instant.now(), Duration.ofMinutes(30));
        org.springframework.mock.web.MockHttpServletRequest servletRequest =
            new org.springframework.mock.web.MockHttpServletRequest();
        org.springframework.web.context.request.ServletWebRequest request =
            new org.springframework.web.context.request.ServletWebRequest(servletRequest);
        org.springframework.web.context.request.RequestContextHolder.setRequestAttributes(request);
        try {
            GatewayRelayCleanup.closeWhenRequestEnds(pump);
        } finally {
            org.springframework.web.context.request.RequestContextHolder.resetRequestAttributes();
        }

        new GatewayRelayCleanup().afterCompletion(request, () -> null);

        assertThat(upstream.closed.await(5, java.util.concurrent.TimeUnit.SECONDS)).isTrue();
        assertThat(pump.isClosed()).isTrue();
    }

    @Test
    void closingThePump_endsARelayWaitingForTheNextChunk() throws Exception {
        StallingUpstream upstream = new StallingUpstream();
        GatewayCloudForwarder.UpstreamPump pump = GatewayCloudForwarder.UpstreamPump.start(
            upstream, Instant.now(), Duration.ofMinutes(30));
        java.util.concurrent.CompletableFuture<Void> relay = java.util.concurrent.CompletableFuture.runAsync(() -> {
            try {
                pump.transferTo(new ByteArrayOutputStream());
            } catch (IOException e) {
                throw new java.io.UncheckedIOException(e);
            }
        });
        Thread.sleep(200);

        pump.close();

        assertThatThrownBy(() -> relay.get(5, java.util.concurrent.TimeUnit.SECONDS))
            .hasCauseInstanceOf(java.io.UncheckedIOException.class);
    }
}
