package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.RequestedModel;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.RequestedModelRepository;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorHfReachabilityClient;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorHfReachabilityClient.HfReachabilityResult;

/**
 * Backfills the Hugging Face gating verdict on registry rows that predate the
 * precheck (or whose check timed out): every row whose {@code is_gated} is
 * still null is re-checked through the orchestrator, and only a decisive
 * answer is recorded — the row is gated when the Hub rejects the repository
 * with the model-gated reason, not gated otherwise. {@code unknown} (Hub
 * timeout) is no verdict and leaves the row empty, so the next sweep — or a
 * later vote, which runs the precheck itself — gets another try.
 *
 * The sweep runs on a daemon thread, not in {@code run()} itself: a slow or
 * unreachable Hub must not delay application startup.
 */
@Component
public class RequestedModelHfStatusSweeper implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(RequestedModelHfStatusSweeper.class);

    private final RequestedModelRepository requestedModelRepository;
    private final OrchestratorHfReachabilityClient hfReachabilityClient;
    private final RequestedModelService requestedModelService;

    public RequestedModelHfStatusSweeper(RequestedModelRepository requestedModelRepository,
                                         OrchestratorHfReachabilityClient hfReachabilityClient,
                                         RequestedModelService requestedModelService) {
        this.requestedModelRepository = requestedModelRepository;
        this.hfReachabilityClient = hfReachabilityClient;
        this.requestedModelService = requestedModelService;
    }

    @Override
    public void run(ApplicationArguments args) {
        Thread sweep = new Thread(this::sweepUnverified, "requested-model-hf-status-sweep");
        sweep.setDaemon(true);
        sweep.start();
    }

    /**
     * Check every registry row that has no verdict yet and record the decisive
     * ones. Skips quickly (no log) when nothing is pending; a Hub timeout
     * ({@code unknown}) leaves the row empty for the next pass.
     */
    public void sweepUnverified() {
        var unverified = requestedModelRepository.findByIsGatedIsNull();
        if (unverified.isEmpty()) {
            return;
        }
        int recorded = 0;
        int stillUnknown = 0;
        for (RequestedModel model : unverified) {
            HfReachabilityResult result = hfReachabilityClient.check(model.getName());
            if (result == null
                || HfReachabilityResult.STATUS_UNKNOWN.equals(result.status())) {
                stillUnknown++;
                continue;
            }
            if (requestedModelService.recordGatedVerdictIfAbsent(model.getId(), isGated(result)) > 0) {
                recorded++;
            }
        }
        log.info("Hugging Face status sweep: {} unverified model(s) checked, {} verdict(s) recorded, {} still unknown",
            unverified.size(), recorded, stillUnknown);
    }

    /**
     * The gating verdict of a decisive precheck result: true only when the Hub
     * rejects the repository with the model-gated reason; false when it is
     * reachable or rejected for any other reason.
     */
    private Boolean isGated(HfReachabilityResult result) {
        return !HfReachabilityResult.STATUS_REACHABLE.equals(result.status())
            && HfReachabilityResult.REASON_MODEL_GATED.equals(result.reasonCode());
    }
}
