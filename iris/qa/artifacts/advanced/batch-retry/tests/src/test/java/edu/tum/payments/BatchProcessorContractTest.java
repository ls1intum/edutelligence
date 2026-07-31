package edu.tum.payments;

import org.junit.jupiter.api.Test;

class BatchProcessorContractTest {
    @Test
    void successfulDuplicatesAreIgnoredPerTenant() {}

    @Test
    void aFailedBatchLeavesEveryBalanceUnchanged() {}

    @Test
    void aFailedBatchCanBeRetriedAfterTheUnderlyingProblemIsFixed() {}
}
