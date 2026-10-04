package de.tum.cit.aet.logos.logoswebservice.common;

/** Translated to a 429 response (with a Retry-After header) by {@link GlobalExceptionHandler}. */
public class RateLimitExceededException extends RuntimeException {

    private final long retryAfterSeconds;

    public RateLimitExceededException(long retryAfterSeconds) {
        super("Rate limit exceeded");
        this.retryAfterSeconds = retryAfterSeconds;
    }

    public long getRetryAfterSeconds() {
        return retryAfterSeconds;
    }
}
