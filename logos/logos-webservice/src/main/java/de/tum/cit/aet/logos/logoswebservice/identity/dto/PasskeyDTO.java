package de.tum.cit.aet.logos.logoswebservice.identity.dto;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.UserPasskey;

/**
 * A passkey as shown to the user (#694). The credential id is an identifier,
 * not a secret; the public key itself is never exposed to the UI.
 */
public record PasskeyDTO(Long id, String label, String credentialId, String createdAt) {

    public static PasskeyDTO fromEntity(UserPasskey passkey) {
        return new PasskeyDTO(
            passkey.getId(),
            passkey.getLabel(),
            passkey.getCredentialId(),
            passkey.getCreatedAt() != null ? passkey.getCreatedAt().toString() : null);
    }
}
