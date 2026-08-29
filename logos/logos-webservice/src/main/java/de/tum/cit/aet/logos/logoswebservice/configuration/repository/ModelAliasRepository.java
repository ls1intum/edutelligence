package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ModelAlias;

public interface ModelAliasRepository extends JpaRepository<ModelAlias, Integer> {

    List<ModelAlias> findByModelId(Integer modelId);

    boolean existsByAliasIgnoreCase(String alias);
}
