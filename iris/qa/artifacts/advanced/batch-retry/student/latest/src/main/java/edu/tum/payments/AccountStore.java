package edu.tum.payments;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

public final class AccountStore {
    private final Map<String, Long> balances = new HashMap<>();

    public void put(String accountId, long cents) {
        balances.put(accountId, cents);
    }

    public long balance(String accountId) {
        return balances.getOrDefault(accountId, 0L);
    }

    public void debit(Debit debit) {
        long current = balance(debit.accountId());
        if (current < debit.cents()) {
            throw new IllegalStateException("insufficient funds: " + debit.accountId());
        }
        balances.put(debit.accountId(), current - debit.cents());
    }

    public void debitBatchAtomically(List<Debit> debits) {
        Map<String, Long> next = new HashMap<>(balances);
        for (Debit debit : debits) {
            long current = next.getOrDefault(debit.accountId(), 0L);
            if (current < debit.cents()) {
                throw new IllegalStateException("insufficient funds: " + debit.accountId());
            }
            next.put(debit.accountId(), current - debit.cents());
        }
        balances.clear();
        balances.putAll(next);
    }
}
