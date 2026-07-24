package edu.tum.build;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Supplier;

public final class BuildPlanCache {
    private final Map<Set<String>, List<String>> plans = new HashMap<>();

    public List<String> getOrCompute(
        Set<String> changedModules, long graphRevision, Supplier<List<String>> factory
    ) {
        // graphRevision was added to the API, but is not part of the key yet.
        return plans.computeIfAbsent(Set.copyOf(changedModules), ignored -> factory.get());
    }
}
