package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Async;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Model;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ModelProvider;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Provider;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.PairLatencyStatsProjection;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.PairTokenPriceProjection;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorNotificationService;

/**
 * Auto-derivation of the L/A/C/Q values for model-provider pairs (issue #651).
 *
 * Derivation rules:
 * <ul>
 *   <li>Latency: p50 over the successful, non-cold-start requests of the last
 *       {@link #STATS_WINDOW_DAYS} days — TTFT (first_token - request), total
 *       (response - request), and TPOT (generation phase / completion tokens).
 *   </li>
 *   <li>Cost (cloud pairs): mean of the available prompt/completion catalogue
 *       prices, in the same per-million unit the model list displays
 *       (price_per_k_token / 100000).</li>
 *   <li>Cost (local pairs): VRAM x latency proxy
 *       (total_vram_mb x total_latency_hours x {@link #LOCAL_COST_PER_MB_HOUR}).
 *       PLACEHOLDER: there is no per-hardware $/h figure in the system yet;
 *       the constant is a rough on-prem amortisation estimate and must be
 *       tuned once real hardware costs are available.</li>
 *   <li>Accuracy and quality: NOT derived — there is no trustworthy signal
 *       yet (benchmark scores and user feedback are future work). Their
 *       weights keep the existing manual/default mechanism.</li>
 * </ul>
 *
 * The per-model latency/cost weight (the unit the classification consumes) is
 * the best (lowest) derived value across the model's pairs, mapped onto the
 * standard relative weight scale. A dimension an admin set manually
 * (models.weight_overrides) is never overwritten.
 */
@Service
public class ModelMetricsService {

    private static final Logger log = LoggerFactory.getLogger(ModelMetricsService.class);

    /** Rolling window of observed requests used for the latency percentiles. */
    static final int STATS_WINDOW_DAYS = 30;

    /** Minimum successful requests per pair before its latency is trusted. */
    static final int MIN_LATENCY_SAMPLES = 10;

    /** PLACEHOLDER local-cost factor, see class javadoc. */
    static final double LOCAL_COST_PER_MB_HOUR = 0.0001;

    /** Same per-million conversion the model list uses for catalogue prices. */
    static final double PRICE_PER_K_TO_USD_PER_MILLION = 100000.0;

    private final ModelProviderRepository modelProviderRepository;
    private final ProviderRepository providerRepository;
    private final ModelRepository modelRepository;
    private final ModelWeightService modelWeightService;
    private final OrchestratorNotificationService orchestratorNotificationService;

    public ModelMetricsService(ModelProviderRepository modelProviderRepository,
                               ProviderRepository providerRepository,
                               ModelRepository modelRepository,
                               ModelWeightService modelWeightService,
                               OrchestratorNotificationService orchestratorNotificationService) {
        this.modelProviderRepository = modelProviderRepository;
        this.providerRepository = providerRepository;
        this.modelRepository = modelRepository;
        this.modelWeightService = modelWeightService;
        this.orchestratorNotificationService = orchestratorNotificationService;
    }

    /**
     * Full derivation run: every model-provider pair, then the model weights.
     * Runs at startup and daily, following the PriceUpdaterService pattern.
     */
    @Scheduled(initialDelay = 0, fixedDelay = 86_400_000)
    public void deriveAllMetrics() {
        log.info("metrics_derivation: starting full refresh");
        for (ModelProvider pair : modelProviderRepository.findAll()) {
            derivePairQuietly(pair);
        }
        boolean weightsChanged = applyDerivedWeightsQuietly();
        if (weightsChanged) {
            orchestratorNotificationService.notifyRefresh(true);
        }
        log.info("metrics_derivation: full refresh complete");
    }

    /**
     * Derive the metrics of one model's pairs and refresh the weights.
     * Triggered whenever a model-provider link is created or removed.
     */
    @Async
    public void deriveForModelAsync(int modelId) {
        try {
            deriveForModel(modelId);
        } catch (Exception e) {
            log.warn("metrics_derivation: async refresh failed for model id={}: {}", modelId, e.getMessage());
        }
    }

    public void deriveForModel(int modelId) {
        for (ModelProvider pair : modelProviderRepository.findByModelId(modelId)) {
            derivePairQuietly(pair);
        }
        boolean weightsChanged = applyDerivedWeightsQuietly();
        if (weightsChanged) {
            orchestratorNotificationService.notifyRefresh(true);
        }
    }

    private void derivePairQuietly(ModelProvider pair) {
        try {
            derivePair(pair);
        } catch (Exception e) {
            log.warn("metrics_derivation: failed for model_id={} provider_id={}: {}",
                pair.getModelId(), pair.getProviderId(), e.getMessage());
        }
    }

    private boolean applyDerivedWeightsQuietly() {
        try {
            return applyDerivedWeights();
        } catch (Exception e) {
            log.warn("metrics_derivation: failed to apply derived weights: {}", e.getMessage());
            return false;
        }
    }

    private void derivePair(ModelProvider pair) {
        int modelId = pair.getModelId();
        int providerId = pair.getProviderId();
        Timestamp since = Timestamp.from(Instant.now().minus(STATS_WINDOW_DAYS, ChronoUnit.DAYS));

        PairLatencyStatsProjection latency = modelProviderRepository.findLatencyStats(modelId, providerId, since);
        int samples = latency.getSamples() != null ? latency.getSamples().intValue() : 0;
        Integer ttftMs = roundMs(latency.getTtftP50Ms());
        Integer totalMs = roundMs(latency.getTotalP50Ms());
        Integer tpotMs = roundMs(modelProviderRepository.findTpotStats(modelId, providerId, since).getTpotP50Ms());

        BigDecimal cost = derivePairCost(modelId, providerId, totalMs, samples);
        modelProviderRepository.updateDerivedMetrics(
            modelId, providerId, ttftMs, totalMs, tpotMs, cost, samples, Instant.now());
    }

    private BigDecimal derivePairCost(int modelId, int providerId, Integer totalLatencyMs, int samples) {
        Provider provider = providerRepository.findById(providerId).orElse(null);
        if (provider == null) return null;

        if (provider.getCloudProviderType() != null) {
            PairTokenPriceProjection prices = modelProviderRepository.findTokenPrices(modelId, providerId);
            List<Double> available = new ArrayList<>();
            if (prices.getInputPricePerK() != null) {
                available.add(prices.getInputPricePerK() / PRICE_PER_K_TO_USD_PER_MILLION);
            }
            if (prices.getOutputPricePerK() != null) {
                available.add(prices.getOutputPricePerK() / PRICE_PER_K_TO_USD_PER_MILLION);
            }
            if (available.isEmpty()) return null;
            double mean = available.stream().mapToDouble(Double::doubleValue).average().orElse(0.0);
            return BigDecimal.valueOf(mean).setScale(6, RoundingMode.HALF_UP);
        }

        // Local (logosnode) pair: VRAM x latency proxy, PLACEHOLDER factor.
        if (provider.getTotalVramMb() == null || totalLatencyMs == null || samples < MIN_LATENCY_SAMPLES) {
            return null;
        }
        double latencyHours = totalLatencyMs / 1000.0 / 3600.0;
        double cost = provider.getTotalVramMb() * latencyHours * LOCAL_COST_PER_MB_HOUR;
        return BigDecimal.valueOf(cost).setScale(6, RoundingMode.HALF_UP);
    }

    /**
     * Re-rank the models that have derived latency/cost values (best value
     * across their pairs wins) onto the standard weight scale and store the
     * result, skipping every dimension the admin overrode manually.
     * Returns true when any weight changed.
     */
    boolean applyDerivedWeights() {
        Map<Integer, Double> latencyValues = new HashMap<>();
        Map<Integer, Double> costValues = new HashMap<>();
        for (ModelProvider pair : modelProviderRepository.findAll()) {
            if (pair.getDerivedSamples() != null && pair.getDerivedSamples() >= MIN_LATENCY_SAMPLES
                    && pair.getDerivedTotalLatencyMs() != null) {
                latencyValues.merge(pair.getModelId(), pair.getDerivedTotalLatencyMs().doubleValue(), Math::min);
            }
            if (pair.getDerivedCostUsdPerMillion() != null) {
                costValues.merge(pair.getModelId(), pair.getDerivedCostUsdPerMillion().doubleValue(), Double::min);
            }
        }

        Map<Integer, Integer> latencyWeights = modelWeightService.rankValuesToWeights(latencyValues);
        Map<Integer, Integer> costWeights = modelWeightService.rankValuesToWeights(costValues);
        if (latencyWeights.isEmpty() && costWeights.isEmpty()) return false;

        List<Model> changed = new ArrayList<>();
        for (Model model : modelRepository.findAll()) {
            Map<String, Boolean> overrides =
                model.getWeightOverrides() != null ? model.getWeightOverrides() : Map.of();
            boolean modelChanged = false;
            Integer latencyWeight = latencyWeights.get(model.getId());
            if (latencyWeight != null && !Boolean.TRUE.equals(overrides.get("latency"))) {
                model.setWeightLatency(latencyWeight);
                modelChanged = true;
            }
            Integer costWeight = costWeights.get(model.getId());
            if (costWeight != null && !Boolean.TRUE.equals(overrides.get("cost"))) {
                model.setWeightCost(costWeight);
                modelChanged = true;
            }
            if (modelChanged) changed.add(model);
        }

        if (changed.isEmpty()) return false;
        modelRepository.saveAll(changed);
        log.info("metrics_derivation: updated weights for {} models (latency ranked: {}, cost ranked: {})",
            changed.size(), latencyWeights.size(), costWeights.size());
        return true;
    }

    private static Integer roundMs(Double ms) {
        return ms == null ? null : (int) Math.round(ms);
    }
}
