package edu.tum.payments;

import java.util.HashSet;
import java.util.Set;

public final class BatchProcessor {
    private final AccountStore accounts;
    private final Set<String> completedRequestIds = new HashSet<>();

    public BatchProcessor(AccountStore accounts) {
        this.accounts = accounts;
    }

    public ProcessResult process(Batch batch) {
        if (completedRequestIds.contains(batch.requestId())) {
            return ProcessResult.ALREADY_APPLIED;
        }
        for (Debit debit : batch.debits()) {
            accounts.debit(debit);
        }
        completedRequestIds.add(batch.requestId());
        return ProcessResult.APPLIED;
    }
}
