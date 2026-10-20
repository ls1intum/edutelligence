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
 * Backfills the Hugging Face verdict on registry rows that predate the
 * precheck (or whose check timed out): every row whose
 * {@code hugging_face_status} is still null is re-checked through the
 * orchestrator, and only a decisive answer ({@code reachable} or
 * {@code rejected}) is recorded. {@code unknown} is no verdict and leaves
 * the row empty, so the next sweep — or a later vote, which runs the precheck
 * itself — gets another try.
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
        var unverified = requestedModelRepository.findByHuggingFaceStatusIsNull();
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
            if (requestedModelService.recordHfVerdictIfAbsent(model.getId(), result.status()) > 0) {
                recorded++;
            }
        }
        log.info("Hugging Face status sweep: {} unverified model(s) checked, {} verdict(s) recorded, {} still unknown",
            unverified.size(), recorded, stillUnknown);
    }
}
