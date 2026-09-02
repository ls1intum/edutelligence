package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.TokenPrice;

public interface TokenPriceRepository extends JpaRepository<TokenPrice, Integer> {
    Optional<TokenPrice> findTopByModelIdAndTypeIdAndProviderIdOrderByValidFromDesc(
            Integer modelId, Integer typeId, Integer providerId);

    /**
     * Closes the current validity of the provider's open price rows. The rows
     * themselves are kept - billing of requests made before the close still
     * matches them - but from this point on no price selection considers them
     * current, so only prices opened after the close (a new generation) count.
     */
    @Modifying
    @Query(value = "UPDATE token_prices SET valid_to = NOW() "
        + "WHERE provider_id = :providerId AND valid_to IS NULL", nativeQuery = true)
    int closeCurrentPricesByProviderId(@Param("providerId") int providerId);
}
