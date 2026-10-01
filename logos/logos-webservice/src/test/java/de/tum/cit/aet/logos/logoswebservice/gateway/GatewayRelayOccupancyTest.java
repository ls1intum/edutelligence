package de.tum.cit.aet.logos.logoswebservice.gateway;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.ByteArrayOutputStream;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

class GatewayRelayOccupancyTest {

    @AfterEach
    void reset() {
        Map<String, Object> snap = GatewayRelayOccupancy.snapshot();
        int active = (Integer) snap.get("active");
        for (int i = 0; i < active; i++) {
            GatewayRelayOccupancy.leave();
        }
        GatewayRelayOccupancy.resetStep();
    }

    @Test
    void trackCountsActivePeakAndResets() throws Exception {
        GatewayRelayOccupancy.resetStep();
        CountDownLatch started = new CountDownLatch(2);
        CountDownLatch release = new CountDownLatch(1);
        StreamingResponseBody body = GatewayRelayOccupancy.track(out -> {
            started.countDown();
            try {
                release.await(5, TimeUnit.SECONDS);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new java.io.IOException("interrupted", e);
            }
            out.write('x');
        });

        ExecutorService pool = Executors.newFixedThreadPool(2);
        try {
            pool.submit(() -> {
                try {
                    body.writeTo(new ByteArrayOutputStream());
                } catch (Exception e) {
                    throw new RuntimeException(e);
                }
            });
            pool.submit(() -> {
                try {
                    body.writeTo(new ByteArrayOutputStream());
                } catch (Exception e) {
                    throw new RuntimeException(e);
                }
            });
            assertThat(started.await(5, TimeUnit.SECONDS)).isTrue();

            Map<String, Object> mid = GatewayRelayOccupancy.snapshot();
            assertThat(mid.get("active")).isEqualTo(2);
            assertThat(mid.get("peak_concurrent_relays")).isEqualTo(2);
            assertThat(mid.get("admitted")).isEqualTo(2);

            release.countDown();
            pool.shutdown();
            assertThat(pool.awaitTermination(5, TimeUnit.SECONDS)).isTrue();

            Map<String, Object> after = GatewayRelayOccupancy.snapshot();
            assertThat(after.get("active")).isEqualTo(0);
            assertThat(after.get("peak_concurrent_relays")).isEqualTo(2);

            GatewayRelayOccupancy.resetStep();
            Map<String, Object> reset = GatewayRelayOccupancy.snapshot();
            assertThat(reset.get("peak_concurrent_relays")).isEqualTo(0);
            assertThat(reset.get("admitted")).isEqualTo(0);
        } finally {
            release.countDown();
            pool.shutdownNow();
        }
    }

    @Test
    void peakSurvivesPartialOverlap() throws Exception {
        GatewayRelayOccupancy.resetStep();
        AtomicInteger sawPeak = new AtomicInteger();
        StreamingResponseBody first = GatewayRelayOccupancy.track(out -> {
            sawPeak.set((Integer) GatewayRelayOccupancy.snapshot().get("active"));
            out.write('a');
        });
        first.writeTo(new ByteArrayOutputStream());
        StreamingResponseBody second = GatewayRelayOccupancy.track(out -> out.write('b'));
        second.writeTo(new ByteArrayOutputStream());

        Map<String, Object> snap = GatewayRelayOccupancy.snapshot();
        assertThat(sawPeak.get()).isEqualTo(1);
        assertThat(snap.get("peak_concurrent_relays")).isEqualTo(1);
        assertThat(snap.get("admitted")).isEqualTo(2);
        assertThat(snap.get("active")).isEqualTo(0);
    }
}
