package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.RequestedModel;

public interface RequestedModelRepository extends JpaRepository<RequestedModel, Integer> {

    Optional<RequestedModel> findByNameIgnoreCase(String name);

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
