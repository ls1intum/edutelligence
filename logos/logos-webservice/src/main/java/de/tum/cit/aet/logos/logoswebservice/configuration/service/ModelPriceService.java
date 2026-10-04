package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;

import org.springframework.stereotype.Service;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ModelProvider;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Provider;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.TokenPrice;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.TokenType;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.TokenPriceRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.TokenTypeRepository;

/**
 * Read side of the catalogue prices that {@link PriceUpdaterService} ingests:
 * current and historic rates for one model, grouped per provider. Backs the
 * Prices tab of the model details page, which hides itself for models served
 * only by local (logosnode) providers.
 */
@Service
public class ModelPriceService {

    private final ModelRepository modelRepository;
    private final ModelProviderRepository modelProviderRepository;
    private final ProviderRepository providerRepository;
    private final TokenPriceRepository tokenPriceRepository;
    private final TokenTypeRepository tokenTypeRepository;

    public ModelPriceService(ModelRepository modelRepository,
                             ModelProviderRepository modelProviderRepository,
                             ProviderRepository providerRepository,
                             TokenPriceRepository tokenPriceRepository,
                             TokenTypeRepository tokenTypeRepository) {
        this.modelRepository = modelRepository;
        this.modelProviderRepository = modelProviderRepository;
        this.providerRepository = providerRepository;
        this.tokenPriceRepository = tokenPriceRepository;
        this.tokenTypeRepository = tokenTypeRepository;
    }

    /**
     * All providers linked to the model with their catalogue price rows,
     * newest rate last within each (quantity, unit, context tier, service
     * tier) dimension so the latest row is the current one.
     *
     * @return empty when the model does not exist
     */
    public Optional<Map<String, Object>> getModelPrices(Integer modelId) {
        if (!modelRepository.existsById(modelId)) {
            return Optional.empty();
        }

        List<ModelProvider> links = modelProviderRepository.findByModelId(modelId);
        List<TokenPrice> prices = tokenPriceRepository.findByModelId(modelId);
        Set<Integer> typeIds = prices.stream().map(TokenPrice::getTypeId).collect(Collectors.toSet());
        Map<Integer, String> quantityById = typeIds.isEmpty()
            ? Map.of()
            : tokenTypeRepository.findAllById(new ArrayList<>(typeIds)).stream()
                .collect(Collectors.toMap(TokenType::getId, TokenType::getName));

        Map<Integer, Provider> providerById = links.isEmpty()
            ? Map.of()
            : providerRepository.findAllById(links.stream().map(ModelProvider::getProviderId).toList())
                .stream()
                .collect(Collectors.toMap(Provider::getId, Function.identity()));

        Map<Integer, List<TokenPrice>> pricesByProvider = prices.stream()
            .filter(price -> price.getProviderId() != null && quantityById.containsKey(price.getTypeId()))
            .collect(Collectors.groupingBy(TokenPrice::getProviderId));

        Comparator<TokenPrice> priceOrder = Comparator
            .comparing((TokenPrice price) -> quantityById.get(price.getTypeId()))
            .thenComparing(TokenPrice::getUnit)
            .thenComparing(TokenPrice::getMinContextTokens)
            .thenComparing(TokenPrice::getServiceTier)
            .thenComparing(TokenPrice::getValidFrom);

        List<Map<String, Object>> providers = links.stream()
            .map(ModelProvider::getProviderId)
            .distinct()
            .map(providerById::get)
            .filter(provider -> provider != null)
            .sorted(Comparator.comparing(Provider::getName,
                Comparator.nullsLast(Comparator.naturalOrder())))
            .map(provider -> toProviderPriceMap(provider,
                pricesByProvider.getOrDefault(provider.getId(), List.of()).stream()
                    .sorted(priceOrder)
                    .toList(),
                quantityById))
            .toList();

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("model_id", modelId);
        result.put("providers", providers);
        return Optional.of(result);
    }

    private Map<String, Object> toProviderPriceMap(Provider provider, List<TokenPrice> prices,
                                                   Map<Integer, String> quantityById) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("provider_id", provider.getId());
        map.put("provider_name", provider.getName());
        map.put("provider_type", provider.getProviderType() != null ? provider.getProviderType().name() : null);
        map.put("cloud_provider_type",
            provider.getCloudProviderType() != null ? provider.getCloudProviderType().name() : null);
        map.put("prices", prices.stream().map(price -> toPriceMap(price, quantityById)).toList());
        return map;
    }

    private Map<String, Object> toPriceMap(TokenPrice price, Map<Integer, String> quantityById) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("quantity", quantityById.get(price.getTypeId()));
        map.put("unit", price.getUnit());
        map.put("min_context_tokens", price.getMinContextTokens());
        map.put("service_tier", price.getServiceTier());
        map.put("price_per_k_unit", price.getPricePerKUnit());
        map.put("valid_from", price.getValidFrom() != null ? price.getValidFrom().toString() : null);
        return map;
    }
}
