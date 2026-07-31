package edu.tum.payments;

public record RetryPolicy(int maxAttempts) {
    public RetryPolicy {
        if (maxAttempts < 1) {
            throw new IllegalArgumentException("maxAttempts must be positive");
        }
    }
}
