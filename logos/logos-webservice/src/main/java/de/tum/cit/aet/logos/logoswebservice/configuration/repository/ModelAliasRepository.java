package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ModelAlias;

public interface ModelAliasRepository extends JpaRepository<ModelAlias, Integer> {

    List<ModelAlias> findByModelId(Integer modelId);

    boolean existsByAliasIgnoreCase(String alias);

    /**
     * Acquires a transaction-scoped advisory lock on the given key, blocking
     * until any other holder's transaction commits or rolls back. Used to
     * serialize the cross-table model-name/alias checks (see
     * {@code ModelService#lockModelAliasNamespace}); released automatically
     * with the surrounding transaction.
     */
    @Query(value = "SELECT pg_advisory_xact_lock(:key)", nativeQuery = true)
    void lockModelAliasNamespace(@Param("key") long key);
}
