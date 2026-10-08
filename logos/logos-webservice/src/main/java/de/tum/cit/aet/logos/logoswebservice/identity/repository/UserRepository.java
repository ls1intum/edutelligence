package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import jakarta.persistence.LockModeType;

public interface UserRepository extends JpaRepository<User, Integer> {

    List<User> findByIsActiveTrue();

    /**
     * Locks the user row until the surrounding transaction ends. Role changes and
     * ownership grants both acquire this lock before their cross-entity check
     * (role vs. team ownership), so the two mutations serialize and cannot race
     * an app_developer into team ownership.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT u FROM User u WHERE u.id = :id")
    Optional<User> findByIdForUpdate(@Param("id") Integer id);

    @Query("SELECT u FROM User u WHERE u.isActive = true AND u.role IN ('logos_admin', 'app_admin')")
    List<User> findAdmins();

    boolean existsByUsername(String username);

    boolean existsByEmailIgnoreCase(String email);

    Optional<User> findByEmailIgnoreCase(String email);

    Optional<User> findFirstByEmailIgnoreCase(String email);

    Optional<User> findByKeycloakId(UUID keycloakId);

    Optional<User> findByUsername(String username);

    List<User> findByKeycloakIdIsNotNull();

    List<User> findByPrenameIgnoreCaseAndNameIgnoreCaseAndKeycloakIdIsNull(String prename, String name);

    @Query("""
        SELECT u FROM User u
        WHERE u.id = (
            SELECT ak.userId FROM ApiKey ak
            WHERE ak.keyValue = :keyValue AND ak.isActive = true
        )
        """)
    Optional<User> findByActiveApiKeyValue(@Param("keyValue") String keyValue);
}
