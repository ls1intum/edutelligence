package edu.tum.payments;

public record Debit(String accountId, long cents) {
    public Debit {
        if (cents <= 0) {
            throw new IllegalArgumentException("cents must be positive");
        }
    }
}
