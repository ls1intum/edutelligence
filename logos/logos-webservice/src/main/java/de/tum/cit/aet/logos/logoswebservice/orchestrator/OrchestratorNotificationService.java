package de.tum.cit.aet.logos.logoswebservice.orchestrator;

import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.client.RestTemplate;

@Service
public class OrchestratorNotificationService {

    private static final Logger log = LoggerFactory.getLogger(OrchestratorNotificationService.class);

    private final RestTemplate restTemplate;

    /**
     * This bean through its proxy. Every caller of {@link #notifyRefresh(boolean, boolean)} is
     * inside a transaction, so the send has to be deferred to after the commit — and a deferred
     * send is a plain method call from a callback, which would bypass the {@code @Async} proxy
     * and put the HTTP round trip on the committing request thread. Going through the proxy
     * keeps it off. Lazy by nature, so it does not close a circular dependency on itself.
     */
    private final ObjectProvider<OrchestratorNotificationService> self;

    @Value("${logos.orchestrator.url:}")
    private String orchestratorUrl;

    @Value("${logos.orchestrator.internal-secret:}")
    private String internalSecret;

    public OrchestratorNotificationService(RestTemplate restTemplate,
                                           ObjectProvider<OrchestratorNotificationService> self) {
        this.restTemplate = restTemplate;
        this.self = self;
    }

    public void notifyRefresh(boolean rebuildClassifier) {
        notifyRefresh(rebuildClassifier, false);
    }

    /**
     * Announce a pipeline refresh to the orchestrator, once the change being announced is
     * actually visible.
     *
     * <p>Every caller runs inside a {@code @Transactional} service method, and the orchestrator
     * answers by reading the database back. Sending before the commit is a race it loses on its
     * own connection: it reads the rows as they were, and a provider that was just added is
     * simply not there. The pass then reports nothing to do — the very symptom the cloud model
     * sync exists to prevent. Deferring to {@code afterCommit} also means a rolled-back change
     * announces nothing, which the immediate send got wrong in the other direction.
     *
     * @param rebuildClassifier whether the model classifier has to be rebuilt
     * @param syncCloudModels   whether a cloud provider itself was added or changed. A new
     *                          provider contributes no models until its {@code /v1/models}
     *                          listing is read, and that otherwise waits for the orchestrator's
     *                          15-minute interval — long enough that an operator reads the empty
     *                          list as a broken sync. The orchestrator schedules the pass and
     *                          answers immediately, so this stays as cheap as a plain refresh.
     */
    public void notifyRefresh(boolean rebuildClassifier, boolean syncCloudModels) {
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    self.getObject().sendRefresh(rebuildClassifier, syncCloudModels);
                }
            });
            return;
        }
        // No transaction in progress: there is nothing to wait for.
        self.getObject().sendRefresh(rebuildClassifier, syncCloudModels);
    }

    /**
     * Tell the orchestrator that a lane lock changed, once the change is
     * committed.
     *
     * <p>The capacity planner serves lane locks from memory and re-reads
     * {@code lane_locks} only in the background every few minutes, so this
     * push is what makes a lock or an unlock take effect at once. Deferred to
     * {@code afterCommit} and sent off the request thread like
     * {@link #notifyRefresh(boolean, boolean)}; a lost push is caught by the
     * planner's next re-read. The sends can arrive out of order, so each
     * carries the change's {@code revision}; the planner ignores a change
     * older than the one it holds for the lane.
     */
    public void notifyLaneLock(int providerId, String laneId, boolean locked, long revision) {
        notifyLaneLock(providerId, laneId, locked, revision, null);
    }

    /**
     * Pushes a lane lock change with the lock's restore record as committed
     * ({@code restore_lanes} as JSON text, or {@code null} for none). The
     * planner takes the record from the push instead of keeping the one it
     * held: a relock that overtakes its unlock must not inherit the lanes of
     * the earlier lock.
     */
    public void notifyLaneLock(int providerId, String laneId, boolean locked, long revision, String restoreLanes) {
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    self.getObject().sendLaneLock(providerId, laneId, locked, revision, restoreLanes);
                }
            });
            return;
        }
        self.getObject().sendLaneLock(providerId, laneId, locked, revision, restoreLanes);
    }

    @Async
    public void sendLaneLock(int providerId, String laneId, boolean locked, long revision, String restoreLanes) {
        if (orchestratorUrl.isBlank() || internalSecret.isBlank()) {
            return;
        }
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.set("Authorization", "Bearer " + internalSecret);
            headers.set("Content-Type", "application/json");
            Map<String, Object> body = new java.util.HashMap<>(
                Map.of("provider_id", providerId, "lane_id", laneId, "locked", locked, "revision", revision));
            body.put("restore_lanes_json", restoreLanes);
            HttpEntity<Map<String, Object>> request = new HttpEntity<>(body, headers);
            restTemplate.postForEntity(orchestratorUrl + "/internal/lane_lock_changed", request, Void.class);
        } catch (Exception e) {
            log.warn("Failed to notify orchestrator of a lane lock change: {}", e.getMessage());
        }
    }

    @Async
    public void sendRefresh(boolean rebuildClassifier, boolean syncCloudModels) {
        postRefresh(rebuildClassifier, syncCloudModels);
    }

    /**
     * Synchronous counterpart of {@link #sendRefresh(boolean, boolean)} for
     * callers that have to report delivery, e.g. the explicit refresh
     * endpoint. The async path swallows failures by design — a background
     * announcement must never fail the request that triggered it — but an
     * operator who pressed "refresh" is owed the truth: false means the
     * orchestrator was not reached and the pass did not start. Acceptance
     * is all that is promised; the model sync pass itself is scheduled on
     * the orchestrator and not awaited (see /internal/cloud_model_sync_status
     * for its completion state).
     */
    public boolean sendRefreshSync(boolean rebuildClassifier, boolean syncCloudModels) {
        return postRefresh(rebuildClassifier, syncCloudModels);
    }

    private boolean postRefresh(boolean rebuildClassifier, boolean syncCloudModels) {
        // Unconfigured stays as quiet as the old fire-and-forget path: a dev
        // webservice without an orchestrator logs nothing on every provider
        // change; the sync caller surfaces the gap as a plain false.
        if (orchestratorUrl.isBlank() || internalSecret.isBlank()) {
            return false;
        }
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.set("Authorization", "Bearer " + internalSecret);
            headers.set("Content-Type", "application/json");
            HttpEntity<Map<String, Object>> request = new HttpEntity<>(
                Map.of("rebuild_classifier", rebuildClassifier, "sync_cloud_models", syncCloudModels), headers
            );
            restTemplate.postForEntity(orchestratorUrl + "/internal/refresh_pipeline", request, Void.class);
            return true;
        } catch (Exception e) {
            log.warn("Failed to notify orchestrator of pipeline refresh: {}", e.getMessage());
            return false;
        }
    }
}
