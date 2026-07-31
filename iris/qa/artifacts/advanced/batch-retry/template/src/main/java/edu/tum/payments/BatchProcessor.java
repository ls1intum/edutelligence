package edu.tum.payments;

public final class BatchProcessor {
    public BatchProcessor(AccountStore accounts) {}

    public ProcessResult process(Batch batch) {
        return ProcessResult.APPLIED;
    }
}
