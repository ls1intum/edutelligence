package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

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
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.PairTpotStatsProjection;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.PairTokenPriceProjection;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorNotificationService;

/**
 * Auto-derivation of the L/A/C/Q values for model-provider pairs.
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
 *       (total_vram_mb x total_latency_hours x {@link #LOCAL_COST_PER_MB_HOUR}),
 *       i.e. USD for one typical request occupying the whole card.
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
 * standard relative weight scale. The cloud and local cost figures use
 * different units (USD per million tokens vs. USD per request), so only the
 * cloud cost is commensurable across pairs and only it feeds the cost
 * ranking — the local figure stays on the pair row for display.
 *
 * A relative scale is only meaningful when the whole population is ranked on
 * it: the write for a dimension is held until every model that has a pair
 * (cost: a cloud pair) has a derived value for that dimension, so the fleet
 * never mixes auto- and manually-ranked scales.
 *
 * A dimension an admin set manually (models.weight_overrides) is never
 * overwritten: the weight write is a targeted UPDATE whose WHERE clause
 * re-checks the override map at write time, so a pin committed concurrently
 * with a derivation run survives, and runs where no value moved are no-ops
 * that do not notify the orchestrator.
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
    private final PriceUpdaterService priceUpdaterService;
    private final OrchestratorNotificationService orchestratorNotificationService;

    public ModelMetricsService(ModelProviderRepository modelProviderRepository,
                               ProviderRepository providerRepository,
                               ModelRepository modelRepository,
                               ModelWeightService modelWeightService,
                               PriceUpdaterService priceUpdaterService,
                               OrchestratorNotificationService orchestratorNotificationService) {
        this.modelProviderRepository = modelProviderRepository;
        this.providerRepository = providerRepository;
        this.modelRepository = modelRepository;
        this.modelWeightService = modelWeightService;
        this.priceUpdaterService = priceUpdaterService;
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

    /**
     * Derivation for a freshly connected model: the catalogue price refresh
     * runs first (synchronously in the async worker), because the cloud cost
     * reads token_prices - a brand-new pair has no price rows yet.
     */
    @Async
    public void deriveAfterPriceRefreshAsync(int modelId) {
        try {
            deriveAfterPriceRefresh(modelId);
        } catch (Exception e) {
            log.warn("metrics_derivation: async refresh failed for model id={}: {}", modelId, e.getMessage());
        }
    }

    public void deriveAfterPriceRefresh(int modelId) {
        Model model = modelRepository.findById(modelId).orElse(null);
        if (model != null && model.getName() != null && !model.getName().isBlank()) {
            priceUpdaterService.updatePricesForModel(modelId, model.getName());
        }
        deriveForModel(modelId);
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

        // Both stats queries return null (not an empty projection) when the
        // pair has no qualifying log entries yet - a freshly linked pair.
        PairLatencyStatsProjection latency = modelProviderRepository.findLatencyStats(modelId, providerId, since);
        int samples = latency != null && latency.getSamples() != null ? latency.getSamples().intValue() : 0;
        Integer ttftMs = latency != null ? roundMs(latency.getTtftP50Ms()) : null;
        Integer totalMs = latency != null ? roundMs(latency.getTotalP50Ms()) : null;
        PairTpotStatsProjection tpot = modelProviderRepository.findTpotStats(modelId, providerId, since);
        Integer tpotMs = tpot != null ? roundMs(tpot.getTpotP50Ms()) : null;

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

        // Local (logosnode) pair: VRAM x latency proxy in USD per request,
        // PLACEHOLDER factor. Display-only - see class javadoc why it does not
        // reach the cost ranking.
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
     * result. See class javadoc for the full rules: fleet-wide scale gating,
     * cloud-only cost ranking, and race-safe, guarded, targeted writes that
     * skip manual pins and no-op when nothing moved.
     * Returns true when any weight actually changed.
     */
    boolean applyDerivedWeights() {
        // Build the per-dimension populations from the pairs table:
        // latency = all pairs, but cost ranking = only cloud pairs.
        Set<Integer> pairedModelIds = new HashSet<>();
        Set<Integer> cloudPairedModelIds = new HashSet<>();
        Set<Integer> cloudProviderIds = providerRepository.findAll().stream()
            .filter(p -> p.getCloudProviderType() != null)
            .map(Provider::getId).collect(Collectors.toSet());
        Map<Integer, Double> latencyValues = new HashMap<>();
        Map<Integer, Double> costValues = new HashMap<>();
        for (ModelProvider pair : modelProviderRepository.findAll()) {
            pairedModelIds.add(pair.getModelId());
            if (cloudProviderIds.contains(pair.getProviderId())) cloudPairedModelIds.add(pair.getModelId());

            if (pair.getDerivedSamples() != null && pair.getDerivedSamples() >= MIN_LATENCY_SAMPLES
                    && pair.getDerivedTotalLatencyMs() != null) {
                latencyValues.merge(pair.getModelId(), pair.getDerivedTotalLatencyMs().doubleValue(), Math::min);
            }
            // Only the cloud cost in $/M tokens is commensurable across pairs,
            // so only it feeds the model-level cost ranking; the local $/request
            // proxy stays display-only on the pair row.
            if (pair.getDerivedCostUsd() != null && cloudProviderIds.contains(pair.getProviderId())) {
                costValues.merge(pair.getModelId(), pair.getDerivedCostUsd().doubleValue(), Double::min);
            }
        }

        // A model without a pair is not in either population, so models without
        // data or traffic stay on their current (manual/default) weight.
        // Under-sampled models are in the latency population (paired) but not in
        // the latency data set (not enough samples), so they'd create a mixed
        // scale -> hold the write for that dimension until full coverage.
        boolean latencyFull = !pairedModelIds.isEmpty() && latencyValues.keySet().containsAll(pairedModelIds);
        boolean costFull = !cloudPairedModelIds.isEmpty() && costValues.keySet().containsAll(cloudPairedModelIds);
        if (!latencyFull && !costFull) return false;
        Map<Integer, Integer> latencyWeights = latencyFull ? modelWeightService.rankValuesToWeights(latencyValues) : Map.of();
        Map<Integer, Integer> costWeights = costFull ? modelWeightService.rankValuesToWeights(costValues) : Map.of();

        int updated = 0;
        for (Model model : modelRepository.findAll()) {
            // Compare first, so a steady-state run is a no-op and we don't
            // saveAll/notify needlessly (even though the entity is loaded in the
            // transaction, we don't dirty it unless there's a real change).
            Integer latencyWeight = latencyWeights.get(model.getId());
            if (latencyWeight != null && !latencyWeight.equals(model.getWeightLatency())) {
                updated += modelRepository.updateWeightLatencyGuarded(model.getId(), latencyWeight);
            }
            Integer costWeight = costWeights.get(model.getId());
            if (costWeight != null && !costWeight.equals(model.getWeightCost())) {
                updated += modelRepository.updateWeightCostGuarded(model.getId(), costWeight);
            }
        }
        if (updated == 0) return false;
        log.info("metrics_derivation: updated {} model weights (latency ranked: {} models, cost ranked: {} models)",
            updated, latencyWeights.size(), costWeights.size());
        return true;
    }

    private static Integer roundMs(Double ms) {
        return ms == null ? null : (int) Math.round(ms);
    }
}
