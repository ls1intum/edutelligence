package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;

public interface UserRepository extends JpaRepository<User, Integer> {

    @Query("SELECT u FROM User u WHERE u.role IN ('logos_admin', 'app_admin')")
    List<User> findAdmins();

    @Query("""
        SELECT u FROM User u
        WHERE u.id = (
            SELECT ak.userId FROM ApiKey ak
            WHERE ak.keyValue = :keyValue AND ak.isActive = true
        )
        """)
    Optional<User> findByActiveApiKeyValue(@Param("keyValue") String keyValue);
}