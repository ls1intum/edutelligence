package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.TokenPrice;

public interface TokenPriceRepository extends JpaRepository<TokenPrice, Integer> {

    Optional<TokenPrice>
    findTopByModelIdAndTypeIdAndProviderIdAndUnitAndMinContextTokensAndServiceTierOrderByValidFromDesc(
            Integer modelId, Integer typeId, Integer providerId,
            String unit, Long minContextTokens, String serviceTier);

    /**
     * Closes the current validity of the provider's open price rows. The rows
     * themselves are kept - billing of requests made before the close still
     * matches them - but from this point on no price selection considers them
     * current, so only prices opened after the close (a new generation) count.
     *
     * The stamp is statement_timestamp(): this update runs in the provider
     * type change's transaction only after that transaction took the
     * provider's advisory lock, and a catalogue price write holding the lock
     * can commit a row while the change waits - a row whose valid_from is
     * later than the change transaction's fixed NOW(). The statement's
     * wall-clock start keeps every closed interval on valid_from <=
     * valid_to, so requests made while such a row was active still bill
     * against it. statement_timestamp() and not clock_timestamp(): the
     * latter is volatile and advances even within this statement, so the
     * prompt, completion, and other rows the update closes could receive
     * different valid_to boundaries, and a request timestamp between two of
     * them would bill only part of its usage. statement_timestamp() is
     * stable within the statement, so one boundary closes every affected
     * row.
     */
    @Modifying
    @Query(value = "UPDATE token_prices SET valid_to = statement_timestamp() "
        + "WHERE provider_id = :providerId AND valid_to IS NULL", nativeQuery = true)
    int closeCurrentPricesByProviderId(@Param("providerId") int providerId);
}
