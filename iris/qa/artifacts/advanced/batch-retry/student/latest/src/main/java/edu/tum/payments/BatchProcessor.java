package edu.tum.payments;

import java.util.HashSet;
import java.util.Set;

public final class BatchProcessor {
    private final AccountStore accounts;
    private final AuditSink audit;
    private final RetryPolicy retryPolicy;
    private final Set<String> completedRequestIds = new HashSet<>();

    public BatchProcessor(AccountStore accounts, AuditSink audit, RetryPolicy retryPolicy) {
        this.accounts = accounts;
        this.audit = audit;
        this.retryPolicy = retryPolicy;
    }

    public synchronized ProcessResult process(Batch batch) {
        if (completedRequestIds.contains(batch.requestId())) {
            audit.append("duplicate:" + batch.requestId());
            return ProcessResult.ALREADY_APPLIED;
        }
        for (Debit debit : batch.debits()) {
            accounts.debit(debit);
        }
        completedRequestIds.add(batch.requestId());
        audit.append("applied:" + batch.tenant() + ":" + batch.requestId());
        return ProcessResult.APPLIED;
    }

    public int configuredAttempts() {
        return retryPolicy.maxAttempts();
    }
}
