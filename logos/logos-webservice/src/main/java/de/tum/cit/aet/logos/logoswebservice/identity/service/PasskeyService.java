package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import jakarta.servlet.http.HttpServletRequest;

import de.tum.cit.aet.logos.logoswebservice.common.ConflictException;
import de.tum.cit.aet.logos.logoswebservice.common.ForbiddenException;
import de.tum.cit.aet.logos.logoswebservice.common.NotFoundException;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.PasskeyDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.UserPasskey;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserPasskeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;

/**
 * User-managed passkeys (WebAuthn credentials), #694: list, add multiple,
 * delete. The browser runs the WebAuthn ceremony; this service issues and
 * verifies the challenges and stores the resulting credentials.
 */
@Service
public class PasskeyService {

    private static final int MAX_LABEL_LENGTH = 255;

    private final UserPasskeyRepository userPasskeyRepository;
    private final UserRepository userRepository;
    private final PasskeyChallengeStore challengeStore;
    private final String configuredRpId;
    private final String rpName;

    public PasskeyService(UserPasskeyRepository userPasskeyRepository,
            UserRepository userRepository,
            PasskeyChallengeStore challengeStore,
            @Value("${logos.auth.passkey.rp-id:}") String configuredRpId,
            @Value("${logos.auth.passkey.rp-name:Logos}") String rpName) {
        this.userPasskeyRepository = userPasskeyRepository;
        this.userRepository = userRepository;
        this.challengeStore = challengeStore;
        this.configuredRpId = configuredRpId;
        this.rpName = rpName;
    }

    public List<PasskeyDTO> listForUser(int userId) {
        return userPasskeyRepository.findByUserIdOrderByCreatedAtAsc(userId).stream()
            .map(PasskeyDTO::fromEntity)
            .toList();
    }

    /**
     * Builds the PublicKeyCredentialCreationOptions for a new registration of
     * this user. The challenge is kept server-side and must be echoed back in
     * the finish call ({@link #register}).
     */
    public Map<String, Object> registrationOptions(int userId, HttpServletRequest request) {
        User user = findUser(userId);
        String rpId = resolveRpId(request);
        String challenge = challengeStore.issue(userId);

        Map<String, Object> userOptions = new LinkedHashMap<>();
        userOptions.put("id", WebAuthnRegistration.base64UrlEncode(userIdBytes(user)));
        userOptions.put("name", user.getUsername());
        userOptions.put("displayName", displayName(user));

        List<Map<String, Object>> excludeCredentials = userPasskeyRepository
            .findByUserIdOrderByCreatedAtAsc(userId).stream()
            .map(passkey -> Map.<String, Object>of("type", "public-key", "id", passkey.getCredentialId()))
            .toList();

        Map<String, Object> options = new LinkedHashMap<>();
        options.put("challenge", challenge);
        options.put("rp", Map.of("id", rpId, "name", rpName));
        options.put("user", userOptions);
        options.put("pubKeyCredParams", List.of(
            Map.of("type", "public-key", "alg", -7), // ES256
            Map.of("type", "public-key", "alg", -257))); // RS256
        options.put("authenticatorSelection",
            Map.of("residentKey", "required", "userVerification", "required"));
        options.put("timeout", 60_000);
        // Ask the authenticator to create a fresh credential instead of returning
        // one of the user's existing passkeys.
        options.put("excludeCredentials", excludeCredentials);
        return options;
    }

    /**
     * Verifies a completed WebAuthn registration and stores the credential.
     *
     * @throws IllegalArgumentException on any verification failure (→ 400)
     * @throws ConflictException when this credential is already registered (→ 409)
     */
    @Transactional
    public PasskeyDTO register(int userId, String credentialId, String clientDataJson,
            String attestationObject, String challenge, String label, HttpServletRequest request) {
        challengeStore.consume(challenge, userId);
        WebAuthnRegistration.Result result = WebAuthnRegistration.verify(
            WebAuthnRegistration.base64UrlDecode(credentialId),
            WebAuthnRegistration.base64UrlDecode(clientDataJson),
            WebAuthnRegistration.base64UrlDecode(attestationObject),
            WebAuthnRegistration.base64UrlDecode(challenge),
            requestOrigin(request),
            resolveRpId(request));
        if (userPasskeyRepository.existsByUserIdAndCredentialId(userId, result.credentialIdBase64Url())) {
            throw new ConflictException("This passkey is already registered.");
        }
        UserPasskey passkey = new UserPasskey();
        passkey.setUserId(userId);
        passkey.setCredentialId(result.credentialIdBase64Url());
        passkey.setPublicKey(result.publicKeyCose());
        passkey.setSignCount(result.signCount());
        passkey.setLabel(truncateLabel(label));
        passkey.setCreatedAt(Instant.now());
        try {
            return PasskeyDTO.fromEntity(userPasskeyRepository.save(passkey));
        } catch (DataIntegrityViolationException e) {
            // Lost a race with a concurrent registration of the same credential.
            throw new ConflictException("This passkey is already registered.");
        }
    }

    /**
     * Deletes the user's passkey. A passkey owned by another user is reported
     * as forbidden (mirrors the API key endpoints); an unknown id 404s.
     */
    @Transactional
    public void delete(long passkeyId, int userId) {
        UserPasskey passkey = userPasskeyRepository.findById(passkeyId)
            .orElseThrow(() -> new NotFoundException("Passkey not found or not owned."));
        if (!passkey.getUserId().equals(userId)) {
            throw new ForbiddenException("You do not own this passkey.");
        }
        userPasskeyRepository.delete(passkey);
    }

    private User findUser(int userId) {
        return userRepository.findById(userId)
            .orElseThrow(() -> new NotFoundException("No user linked to this key."));
    }

    /**
     * Relying party id for this request: the configured value when set, else
     * the request host — mirroring the UI's fallback to window.location.hostname
     * so dev/localhost works without configuration.
     */
    String resolveRpId(HttpServletRequest request) {
        if (configuredRpId != null && !configuredRpId.isBlank()) {
            return configuredRpId.strip();
        }
        return request.getServerName();
    }

    /**
     * Origin a registration must have been created in. Browsers always send the
     * Origin header on POSTs (same-origin included), so it is the authoritative
     * value; scheme://host is only a fallback for clients without one.
     */
    static String requestOrigin(HttpServletRequest request) {
        String origin = request.getHeader("Origin");
        if (origin != null && !origin.isBlank()) {
            return origin.strip();
        }
        int port = request.getServerPort();
        boolean defaultPort = ("http".equalsIgnoreCase(request.getScheme()) && port == 80)
            || ("https".equalsIgnoreCase(request.getScheme()) && port == 443);
        return request.getScheme() + "://" + request.getServerName()
            + (defaultPort ? "" : ":" + port);
    }

    /**
     * Stable opaque WebAuthn user id (1–64 bytes): the Keycloak user id when
     * known, else a synthetic per-user value.
     */
    private static byte[] userIdBytes(User user) {
        if (user.getKeycloakId() != null) {
            byte[] bytes = new byte[16];
            long mostSignificant = user.getKeycloakId().getMostSignificantBits();
            long leastSignificant = user.getKeycloakId().getLeastSignificantBits();
            for (int i = 0; i < 8; i++) {
                bytes[i] = (byte) (mostSignificant >>> (56 - 8 * i));
                bytes[8 + i] = (byte) (leastSignificant >>> (56 - 8 * i));
            }
            return bytes;
        }
        return ("logos-user-" + user.getId()).getBytes(StandardCharsets.UTF_8);
    }

    private static String displayName(User user) {
        String full = ((user.getPrename() == null ? "" : user.getPrename()) + " "
            + (user.getName() == null ? "" : user.getName())).strip();
        return full.isEmpty() ? user.getUsername() : full;
    }

    private static String truncateLabel(String label) {
        if (label == null || label.isBlank()) {
            return null;
        }
        String trimmed = label.strip();
        return trimmed.length() <= MAX_LABEL_LENGTH ? trimmed : trimmed.substring(0, MAX_LABEL_LENGTH);
    }
}
