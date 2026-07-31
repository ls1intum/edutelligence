package edu.tum.payments;

import java.util.List;

public record Batch(String tenant, String requestId, List<Debit> debits) {}
