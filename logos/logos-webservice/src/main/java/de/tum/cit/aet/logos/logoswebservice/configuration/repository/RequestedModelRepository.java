package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.RequestedModel;

public interface RequestedModelRepository extends JpaRepository<RequestedModel, Integer> {

    Optional<RequestedModel> findByNameIgnoreCase(String name);

    /** Registry rows without a Hugging Face verdict yet (never checked, or the check timed out). */
    List<RequestedModel> findByIsGatedIsNull();

    /**
     * Record a decisive Hugging Face gating verdict on a row that has none
     * yet. The condition keeps a concurrent vote (which stores its own fresh
     * verdict) from being clobbered by a stale sweep.
     *
     * @return the number of rows updated (0 when the row already has a verdict)
     */
    @Modifying
    @Query("UPDATE RequestedModel m SET m.isGated = :status WHERE m.id = :id AND m.isGated IS NULL")
    int setIsGatedIfNull(@Param("id") Integer id, @Param("status") Boolean status);

    /**
     * Acquires a transaction-scoped advisory lock on the given key, blocking
     * until any other holder's transaction commits or rolls back. Used to
     * serialize the check-and-increment in {@code RequestedModelService} so two
     * simultaneous requests for the same never-before-seen model cannot both
     * insert; released automatically with the surrounding transaction.
     */
    @Query(value = "SELECT pg_advisory_xact_lock(:key)", nativeQuery = true)
    void lockRequestedModelsNamespace(@Param("key") long key);
}
