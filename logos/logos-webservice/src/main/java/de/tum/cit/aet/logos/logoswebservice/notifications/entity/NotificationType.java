package de.tum.cit.aet.logos.logoswebservice.notifications.entity;

import java.util.Optional;

/**
 * The fixed vocabulary of events the notification system can carry.
 *
 * <p>Adding a new kind of event is a one-line change here plus a producer
 * that calls the publish API with the new value — the storage, fan-out and
 * read paths do not need to know about the meaning of any specific type.
 *
 * <p>The constant names are the stored values (as on the wire), so the
 * {@code @Enumerated(EnumType.STRING)} mapping persists them verbatim.
 */
public enum NotificationType {

    /** A Logos deployment finished (audience: Logos admin). */
    deployment,
    /** A Logos deployment failed or was rolled back and needs a look (audience: Logos admin). */
    deployment_failed,
    /** A previously requested model is now available (audience: Developer). */
    model_request_succeeded,
    /** A batch job reached a terminal state (audience: App admin). */
    batch_job_finished,
    /** A monthly budget was hit (audience: App admin). */
    budget_hit,
    /** New models became available to a team (audience: Developer). */
    new_models_available,
    /** A developer requested a model the team cannot use yet (audience: App admin). */
    model_access_requested,
    /** Benchmark results are ready for review (audience: Logos admin). */
    benchmark_result_ready,
    /** A calibration run failed (audience: Logos admin). */
    calibration_failed;

    /** @return the type whose value equals {@code value}, if any. */
    public static Optional<NotificationType> fromValue(String value) {
        if (value == null) {
            return Optional.empty();
        }
        try {
            return Optional.of(NotificationType.valueOf(value));
        } catch (IllegalArgumentException e) {
            return Optional.empty();
        }
    }
}
