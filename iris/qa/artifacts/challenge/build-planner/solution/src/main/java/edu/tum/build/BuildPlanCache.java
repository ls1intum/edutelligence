package edu.tum.build;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Supplier;

public final class BuildPlanCache {
    private record Key(Set<String> changedModules, long graphRevision) {}
    private final Map<Key, List<String>> plans = new HashMap<>();

    public List<String> getOrCompute(
        Set<String> changedModules, long graphRevision, Supplier<List<String>> factory
    ) {
        var key = new Key(Set.copyOf(changedModules), graphRevision);
        return plans.computeIfAbsent(key, ignored -> factory.get());
    }
}
