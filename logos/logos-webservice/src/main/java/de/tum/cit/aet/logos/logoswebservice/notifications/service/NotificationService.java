package de.tum.cit.aet.logos.logoswebservice.notifications.service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.notifications.channel.NotificationChannelRegistry;
import de.tum.cit.aet.logos.logoswebservice.notifications.dto.NotificationResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.notifications.dto.PublishNotificationRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.notifications.dto.NotificationTargetDTO;
import de.tum.cit.aet.logos.logoswebservice.notifications.entity.Notification;
import de.tum.cit.aet.logos.logoswebservice.notifications.entity.NotificationRead;
import de.tum.cit.aet.logos.logoswebservice.notifications.entity.NotificationRecipient;
import de.tum.cit.aet.logos.logoswebservice.notifications.entity.NotificationType;
import de.tum.cit.aet.logos.logoswebservice.notifications.entity.RecipientKind;
import de.tum.cit.aet.logos.logoswebservice.notifications.repository.NotificationReadRepository;
import de.tum.cit.aet.logos.logoswebservice.notifications.repository.NotificationRecipientRepository;
import de.tum.cit.aet.logos.logoswebservice.notifications.repository.NotificationRepository;

/**
 * The publish and read halves of the notification system.
 *
 * <p>Persisting the notification and its recipients is one transaction; the
 * channel fan-out is deferred to {@code afterCommit} so a delivery that reads
 * the database back never sees an uncommitted row, and a rolled-back publish
 * delivers nothing (mirrors {@code OrchestratorNotificationService}).
 */
@Service
public class NotificationService {

    private static final String SOURCE_WEB = "webservice";
    private static final String SOURCE_ORCH = "orchestrator";

    private final NotificationRepository notifications;
    private final NotificationReadRepository reads;
    private final NotificationRecipientRepository recipients;
    private final NotificationChannelRegistry channelRegistry;
    private final ObjectMapper objectMapper;
    private final NotificationMapper mapper;

    public NotificationService(
        NotificationRepository notifications,
        NotificationReadRepository reads,
        NotificationRecipientRepository recipients,
        NotificationChannelRegistry channelRegistry,
        ObjectMapper objectMapper,
        NotificationMapper mapper) {
        this.notifications = notifications;
        this.reads = reads;
        this.recipients = recipients;
        this.channelRegistry = channelRegistry;
        this.objectMapper = objectMapper;
        this.mapper = mapper;
    }

    /**
     * Persist a notification and its fan-out targets, then dispatch to the
     * registered channels after commit.
     *
     * @return the new notification id
     * @throws IllegalArgumentException on an unknown type, missing title, no
     *         targets, an invalid source, or a non-serializable payload
     */
    @Transactional
    public Long publish(PublishNotificationRequestDTO req) {
        NotificationType type = NotificationType.fromValue(req.type())
            .orElseThrow(() -> new IllegalArgumentException("Unknown notification type: " + req.type()));
        if (req.title() == null || req.title().isBlank()) {
            throw new IllegalArgumentException("title is required");
        }
        if (req.targets() == null || req.targets().isEmpty()) {
            throw new IllegalArgumentException("At least one target is required");
        }
        String source = resolveSource(req.source());
        List<NotificationRecipient> recipientRows = toRecipientRows(req.targets());

        Notification n = new Notification();
        n.setType(type);
        n.setTitle(req.title());
        n.setBody(req.body());
        n.setSource(source);
        n.setActorUserId(req.actorUserId());
        n.setCreatedAt(Instant.now());
        if (req.payload() != null && !req.payload().isEmpty()) {
            n.setPayload(writeJson(req.payload()));
        }
        Notification saved = notifications.save(n);

        recipientRows.forEach(r -> r.setNotificationId(saved.getId()));
        recipients.saveAll(recipientRows);

        final Notification delivered = saved;
        final List<NotificationRecipient> deliveredRecipients = recipientRows;
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                channelRegistry.dispatch(delivered, deliveredRecipients);
            }
        });
        return saved.getId();
    }

    /**
     * Publish from a component inside the application server, e.g.
     * {@code publish(NotificationType.budget_hit, "Budget hit", body, Map.of("team_id", id),
     * List.of(NotificationTargetDTO.role(Role.APP_ADMIN)))}. Joins the caller's
     * transaction, so a rolled-back producer publishes nothing.
     *
     * @return the new notification id
     */
    @Transactional
    public Long publish(NotificationType type, String title, String body, Map<String, Object> payload,
                        List<NotificationTargetDTO> targets) {
        return publish(new PublishNotificationRequestDTO(
            type.name(), title, body, payload, SOURCE_WEB, null, targets));
    }

    @Transactional(readOnly = true)
    public Page<NotificationResponseDTO> listMine(Integer userId, String role, List<Integer> teamIds,
        boolean unreadOnly, Pageable pageable) {
        Page<Notification> page = notifications.findForUser(
            userId, role, teamIds, unreadOnly,
            RecipientKind.user, RecipientKind.role, RecipientKind.team, pageable);
        List<Long> pageIds = page.getContent().stream().map(Notification::getId).toList();
        Set<Long> readIds = pageIds.isEmpty() ? Set.of()
            : reads.findByUserIdAndNotificationIdIn(userId, pageIds).stream()
                .map(NotificationRead::getNotificationId)
                .collect(Collectors.toSet());
        return page.map(n -> mapper.toDto(n, readIds.contains(n.getId())));
    }

    @Transactional(readOnly = true)
    public long unreadCount(Integer userId, String role, List<Integer> teamIds) {
        return notifications.countForUser(
            userId, role, teamIds, true,
            RecipientKind.user, RecipientKind.role, RecipientKind.team);
    }

    /**
     * Mark a single notification read for the user.
     *
     * @return false if the notification does not exist or is not addressed to
     *         the user (the caller maps both to the same 404, so ids outside
     *         the inbox stay hidden), true once it is (or already was) read
     */
    @Transactional
    public boolean markRead(Integer userId, String role, List<Integer> teamIds, Long notificationId) {
        if (!notifications.existsForUser(notificationId, userId, role, teamIds,
                RecipientKind.user, RecipientKind.role, RecipientKind.team)) {
            return false;
        }
        reads.insertIfAbsent(notificationId, userId);
        return true;
    }

    /**
     * Mark every notification addressed to the user read, in one statement
     * that reads the user's team memberships itself.
     */
    @Transactional
    public void markAllRead(Integer userId, String role) {
        reads.insertAllAddressed(userId, role);
    }

    /**
     * Validate every target and turn it into a recipient row, before anything
     * is persisted. A target without a usable address could never match an
     * inbox, so it is rejected rather than stored; repeated targets collapse
     * to one row.
     */
    private List<NotificationRecipient> toRecipientRows(List<NotificationTargetDTO> targets) {
        Set<String> seen = new LinkedHashSet<>();
        List<NotificationRecipient> rows = new ArrayList<>();
        for (NotificationTargetDTO target : targets) {
            if (target == null || target.kind() == null) {
                throw new IllegalArgumentException("Every target needs a kind");
            }
            RecipientKind kind = RecipientKind.fromValue(target.kind())
                .orElseThrow(() -> new IllegalArgumentException("Unknown recipient kind: " + target.kind()));
            NotificationRecipient r = new NotificationRecipient();
            r.setRecipientKind(kind);
            if (kind == RecipientKind.role) {
                String role = target.role();
                if (role == null || Arrays.stream(Role.values()).noneMatch(known -> known.matches(role))) {
                    throw new IllegalArgumentException("A role target needs a known role, got: " + role);
                }
                r.setRecipientRole(role);
            } else {
                if (target.id() == null) {
                    throw new IllegalArgumentException("A " + kind.name() + " target needs an id");
                }
                r.setRecipientId(target.id());
            }
            String key = kind.name() + ":" + r.getRecipientId() + ":" + r.getRecipientRole();
            if (seen.add(key)) {
                rows.add(r);
            }
        }
        return rows;
    }

    private String resolveSource(String source) {
        if (source == null || source.isBlank()) {
            return SOURCE_WEB;
        }
        if (SOURCE_WEB.equals(source) || SOURCE_ORCH.equals(source)) {
            return source;
        }
        throw new IllegalArgumentException("source must be 'webservice' or 'orchestrator'");
    }

    private String writeJson(Map<String, Object> payload) {
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (JsonProcessingException e) {
            throw new IllegalArgumentException("payload must be JSON-serializable", e);
        }
    }
}
