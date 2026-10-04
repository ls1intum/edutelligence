package de.tum.cit.aet.logos.logoswebservice.websocket;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * The content signature that decides whether the request feed of a session is
 * re-pushed.
 *
 * The push runs every two seconds and is skipped whenever the signature
 * repeats, so every field the feed renders has to be part of the signature —
 * a change to a field that is left out never reaches the page and the row
 * keeps showing the state of the last push.
 */
class StatsV2WebSocketHandlerSigTest {

    /** A row the way {@code RequestLogService} hands it out: absent values are null. */
    private static Map<String, Object> row(String requestId, String provider, String scheduledTs) {
        Map<String, Object> r = new LinkedHashMap<>();
        r.put("request_id", requestId);
        r.put("status", "pending");
        r.put("provider_name", provider);
        r.put("model_name", "model-a");
        r.put("is_cloud", false);
        r.put("scheduled_ts", scheduledTs);
        r.put("request_complete_ts", null);
        r.put("prompt_tokens", null);
        r.put("completion_tokens", null);
        r.put("total_tokens", null);
        r.put("cost_microcents", null);
        return r;
    }

    private static Map<String, Object> page(Map<String, Object>... rows) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("requests", List.of(rows));
        return payload;
    }

    @Test
    void identicalPagesHaveIdenticalSignatures() {
        assertThat(StatsV2WebSocketHandler.requestsSig(page(row("r-1", "gpu-01", null))))
            .isEqualTo(StatsV2WebSocketHandler.requestsSig(page(row("r-1", "gpu-01", null))));
    }

    @Test
    void aProviderChangeAloneChangesTheSignature() {
        // The row carries the deployment the request was made for from enqueue
        // time; the provider that actually serves it is only written once the
        // request is scheduled. When that is the only thing that moved, the
        // page must still be pushed — otherwise the row keeps the provider it
        // showed while queued.
        assertThat(StatsV2WebSocketHandler.requestsSig(page(row("r-1", "gpu-02", null))))
            .isNotEqualTo(StatsV2WebSocketHandler.requestsSig(page(row("r-1", "gpu-01", null))));
    }

    @Test
    void gainingAProviderFromNoneChangesTheSignature() {
        // A freshly enqueued row has no provider yet; the enqueue-time write
        // fills it in moments later. That is a change too, not a repeat.
        assertThat(StatsV2WebSocketHandler.requestsSig(page(row("r-1", "gpu-01", null))))
            .isNotEqualTo(StatsV2WebSocketHandler.requestsSig(page(row("r-1", null, null))));
    }

    @Test
    void aModelChangeAloneChangesTheSignature() {
        // Scheduling re-resolves the model together with the provider, so a
        // re-routed request changes its model while every timestamp on the row
        // stays put. Without the model in the signature the push is skipped and
        // the row keeps naming the model the request was enqueued for.
        Map<String, Object> rerouted = row("r-1", "gpu-01", null);
        rerouted.put("model_name", "model-b");

        assertThat(StatsV2WebSocketHandler.requestsSig(page(rerouted)))
            .isNotEqualTo(StatsV2WebSocketHandler.requestsSig(page(row("r-1", "gpu-01", null))));
    }

    @Test
    void aCloudLocalFlipAloneChangesTheSignature() {
        // The Cloud/Local badge is derived from the provider's type, so a
        // re-route between a local and a cloud provider must be visible to the
        // signature even though the name field is unchanged.
        Map<String, Object> local = row("r-1", "upstream", null);
        Map<String, Object> cloud = row("r-1", "upstream", null);
        cloud.put("is_cloud", true);
        assertThat(StatsV2WebSocketHandler.requestsSig(page(cloud)))
            .isNotEqualTo(StatsV2WebSocketHandler.requestsSig(page(local)));
    }

    @Test
    void aScheduledTimestampChangeStillChangesTheSignature() {
        // Regression: the queued-to-running transition must keep being
        // detected once the provider fields joined the signature.
        assertThat(StatsV2WebSocketHandler.requestsSig(page(row("r-1", "gpu-01", "2026-08-28T10:15:30Z"))))
            .isNotEqualTo(StatsV2WebSocketHandler.requestsSig(page(row("r-1", "gpu-01", null))));
    }

    @Test
    void aCompletionStillChangesTheSignature() {
        Map<String, Object> completed = row("r-1", "gpu-01", "2026-08-28T10:15:30Z");
        completed.put("status", "success");
        completed.put("request_complete_ts", "2026-08-28T10:15:42Z");
        assertThat(StatsV2WebSocketHandler.requestsSig(page(completed)))
            .isNotEqualTo(StatsV2WebSocketHandler.requestsSig(page(row("r-1", "gpu-01", "2026-08-28T10:15:30Z"))));
    }

    @Test
    void aGrowingTokenCountStillChangesTheSignature() {
        // Regression: usage of a streaming request moves without any status or
        // timestamp changing — the token and cost line must keep moving.
        Map<String, Object> grown = row("r-1", "gpu-01", "2026-08-28T10:15:30Z");
        grown.put("completion_tokens", 42);
        assertThat(StatsV2WebSocketHandler.requestsSig(page(grown)))
            .isNotEqualTo(StatsV2WebSocketHandler.requestsSig(page(row("r-1", "gpu-01", "2026-08-28T10:15:30Z"))));
    }

    @Test
    void anEmptyPageSignsStable() {
        assertThat(StatsV2WebSocketHandler.requestsSig(page()))
            .isEqualTo(StatsV2WebSocketHandler.requestsSig(page()));
    }
}
