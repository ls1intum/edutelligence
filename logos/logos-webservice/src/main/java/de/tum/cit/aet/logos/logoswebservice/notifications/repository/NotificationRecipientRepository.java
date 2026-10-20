package de.tum.cit.aet.logos.logoswebservice.notifications.repository;

import org.springframework.data.jpa.repository.JpaRepository;

import de.tum.cit.aet.logos.logoswebservice.notifications.entity.NotificationRecipient;

public interface NotificationRecipientRepository extends JpaRepository<NotificationRecipient, Long> {
}
