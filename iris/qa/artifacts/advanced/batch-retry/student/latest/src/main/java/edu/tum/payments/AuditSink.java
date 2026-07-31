package edu.tum.payments;

import java.util.ArrayList;
import java.util.List;

public final class AuditSink {
    private final List<String> entries = new ArrayList<>();

    public void append(String entry) {
        entries.add(entry);
    }

    public List<String> entries() {
        return List.copyOf(entries);
    }
}
