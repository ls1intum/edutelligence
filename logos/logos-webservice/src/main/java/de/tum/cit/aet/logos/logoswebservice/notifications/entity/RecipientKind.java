package de.tum.cit.aet.logos.logoswebservice.notifications.entity;

import java.util.Optional;

/**
 * What a notification's fan-out target refers to.
 *
 * <p>A target is either a single user ({@link #user}), a whole team
 * ({@link #team}) or everyone holding a role ({@link #role}). The two value
 * columns on the recipient row are read according to the kind: {@code id}
 * for user/team, {@code role} for role.
 *
 * <p>The constant names are the stored values (as on the wire), so the
 * {@code @Enumerated(EnumType.STRING)} mapping persists them verbatim.
 */
public enum RecipientKind {

    user,
    team,
    role;

    /** @return the kind whose value equals {@code value}, if any. */
    public static Optional<RecipientKind> fromValue(String value) {
        if (value == null) {
            return Optional.empty();
        }
        try {
            return Optional.of(RecipientKind.valueOf(value));
        } catch (IllegalArgumentException e) {
            return Optional.empty();
        }
    }
}
