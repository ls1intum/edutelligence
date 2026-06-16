package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Policy;

public interface PolicyRepository extends JpaRepository<Policy, Integer> {

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT id, api_key_id, team_id, name, description,
            threshold_privacy::text AS threshold_privacy,
            threshold_latency, threshold_accuracy,
            threshold_cost, threshold_quality, priority, topic
        FROM policies
        """, nativeQuery = true)
    List<PolicyProjection> findAllForAdmin();

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT id, api_key_id, team_id, name, description,
            threshold_privacy::text AS threshold_privacy,
            threshold_latency, threshold_accuracy,
            threshold_cost, threshold_quality, priority, topic
        FROM policies WHERE id = :policyId
        """, nativeQuery = true)
    Optional<PolicyProjection> findByIdForAdmin(@Param("policyId") int policyId);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT DISTINCT p.id, p.api_key_id, p.team_id, p.name, p.description,
            p.threshold_privacy::text AS threshold_privacy,
            p.threshold_latency, p.threshold_accuracy,
            p.threshold_cost, p.threshold_quality, p.priority, p.topic
        FROM policies p
        JOIN api_keys ak ON (p.api_key_id = ak.id OR p.team_id = ak.team_id)
        WHERE ak.user_id = :userId AND ak.is_active = true
        """, nativeQuery = true)
    List<PolicyProjection> findAllForUser(@Param("userId") int userId);

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT DISTINCT p.id, p.api_key_id, p.team_id, p.name, p.description,
            p.threshold_privacy::text AS threshold_privacy,
            p.threshold_latency, p.threshold_accuracy,
            p.threshold_cost, p.threshold_quality, p.priority, p.topic
        FROM policies p
        JOIN api_keys ak ON (p.api_key_id = ak.id OR p.team_id = ak.team_id)
        WHERE ak.user_id = :userId AND ak.is_active = true AND p.id = :policyId
        """, nativeQuery = true)
    Optional<PolicyProjection> findByIdForUser(@Param("policyId") int policyId,
                                               @Param("userId") int userId);
}
