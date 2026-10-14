package de.tum.cit.aet.logos.logoswebservice.notifications.controller;

import java.util.List;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMember;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;
import de.tum.cit.aet.logos.logoswebservice.notifications.dto.NotificationResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.notifications.service.NotificationService;

/**
 * The user's own inbox: list, unread count, and read markers. Authenticated
 * with a Keycloak JWT like the rest of the management API; the notification
 * is always read for the caller, never for anyone else.
 */
@RestController
public class NotificationController {

    private static final int MAX_PAGE_SIZE = 100;

    private final NotificationService service;
    private final TeamMemberRepository teamMembers;

    public NotificationController(NotificationService service, TeamMemberRepository teamMembers) {
        this.service = service;
        this.teamMembers = teamMembers;
    }

    @GetMapping("/me/notifications")
    public ResponseEntity<Page<NotificationResponseDTO>> list(
            @RequestAttribute("authContext") AuthContext auth,
            @RequestParam(defaultValue = "false") boolean unreadOnly,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "50") int size) {
        if (auth.userId() == null) {
            return ResponseEntity.ok(Page.empty());
        }
        if (size > MAX_PAGE_SIZE) {
            throw new IllegalArgumentException("size must be <= " + MAX_PAGE_SIZE);
        }
        List<Integer> teamIds = teamIdsFor(auth.userId());
        Page<NotificationResponseDTO> result = service.listMine(
            auth.userId(), auth.role(), teamIds, unreadOnly, PageRequest.of(page, size));
        return ResponseEntity.ok(result);
    }

    @GetMapping("/me/notifications/unread-count")
    public ResponseEntity<Long> unreadCount(@RequestAttribute("authContext") AuthContext auth) {
        if (auth.userId() == null) {
            return ResponseEntity.ok(0L);
        }
        long count = service.unreadCount(auth.userId(), auth.role(), teamIdsFor(auth.userId()));
        return ResponseEntity.ok(count);
    }

    @PostMapping("/me/notifications/{id}/read")
    public ResponseEntity<Void> markRead(
            @RequestAttribute("authContext") AuthContext auth,
            @PathVariable Long id) {
        if (auth.userId() == null) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND).build();
        }
        boolean ok = service.markRead(auth.userId(), auth.role(), teamIdsFor(auth.userId()), id);
        return ok ? ResponseEntity.ok().build()
                  : ResponseEntity.status(HttpStatus.NOT_FOUND).build();
    }

    @PostMapping("/me/notifications/read-all")
    public ResponseEntity<Void> markAllRead(@RequestAttribute("authContext") AuthContext auth) {
        if (auth.userId() != null) {
            service.markAllRead(auth.userId(), auth.role());
        }
        return ResponseEntity.ok().build();
    }

    private List<Integer> teamIdsFor(Integer userId) {
        return teamMembers.findById_UserId(userId).stream()
            .map(TeamMember::getId)
            .map(id -> id.getTeamId())
            .toList();
    }
}
