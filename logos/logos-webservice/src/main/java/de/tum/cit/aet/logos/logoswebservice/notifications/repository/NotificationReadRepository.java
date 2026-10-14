package de.tum.cit.aet.logos.logoswebservice.notifications.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;

import de.tum.cit.aet.logos.logoswebservice.notifications.entity.NotificationRead;

public interface NotificationReadRepository extends JpaRepository<NotificationRead, Long> {

    List<NotificationRead> findByUserId(Integer userId);

    boolean existsByNotificationIdAndUserId(Long notificationId, Integer userId);
}
