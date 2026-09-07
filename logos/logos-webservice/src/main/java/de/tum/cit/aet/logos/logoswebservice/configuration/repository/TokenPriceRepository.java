package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.TokenPrice;

public interface TokenPriceRepository extends JpaRepository<TokenPrice, Integer> {

    Optional<TokenPrice>
    findTopByModelIdAndTypeIdAndProviderIdAndUnitAndMinContextTokensAndServiceTierOrderByValidFromDesc(
            Integer modelId, Integer typeId, Integer providerId,
            String unit, Long minContextTokens, String serviceTier);
}
