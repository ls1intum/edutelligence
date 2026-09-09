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

    @Async
    public void sendRefresh(boolean rebuildClassifier, boolean syncCloudModels) {
        if (orchestratorUrl.isBlank() || internalSecret.isBlank()) {
            return;
        }
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.set("Authorization", "Bearer " + internalSecret);
            headers.set("Content-Type", "application/json");
            HttpEntity<Map<String, Object>> request = new HttpEntity<>(
                Map.of("rebuild_classifier", rebuildClassifier, "sync_cloud_models", syncCloudModels), headers
            );
            restTemplate.postForEntity(orchestratorUrl + "/internal/refresh_pipeline", request, Void.class);
        } catch (Exception e) {
            log.warn("Failed to notify orchestrator of pipeline refresh: {}", e.getMessage());
        }
    }
}
