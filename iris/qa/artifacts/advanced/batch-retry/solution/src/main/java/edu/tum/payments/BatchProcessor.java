package edu.tum.payments;

import java.util.HashSet;
import java.util.Set;

public final class BatchProcessor {
    private final AccountStore accounts;
    private final Set<BatchKey> completed = new HashSet<>();

    public BatchProcessor(AccountStore accounts) {
        this.accounts = accounts;
    }

    public synchronized ProcessResult process(Batch batch) {
        BatchKey key = new BatchKey(batch.tenant(), batch.requestId());
        if (completed.contains(key)) {
            return ProcessResult.ALREADY_APPLIED;
        }
        accounts.debitBatchAtomically(batch.debits());
        completed.add(key);
        return ProcessResult.APPLIED;
    }
}
