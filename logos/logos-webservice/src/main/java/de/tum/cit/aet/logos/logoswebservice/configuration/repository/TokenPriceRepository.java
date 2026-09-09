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
     *
     * The stamp is clock_timestamp(), not NOW(): this update runs in the
     * provider type change's transaction only after that transaction took the
     * provider's advisory lock, and a catalogue price write holding the lock
     * can commit a row while the change waits - a row whose valid_from is
     * later than the change transaction's fixed NOW(). Stamping with the
     * wall-clock time of the close keeps every closed interval on
     * valid_from <= valid_to, so requests made while such a row was active
     * still bill against it.
     */
    @Modifying
    @Query(value = "UPDATE token_prices SET valid_to = clock_timestamp() "
        + "WHERE provider_id = :providerId AND valid_to IS NULL", nativeQuery = true)
    int closeCurrentPricesByProviderId(@Param("providerId") int providerId);
}
