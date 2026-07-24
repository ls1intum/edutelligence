package edu.tum.build;

import java.util.List;
import java.util.Set;
import java.util.function.Supplier;

public final class BuildPlanCache {
    public List<String> getOrCompute(
        Set<String> changedModules, long graphRevision, Supplier<List<String>> factory
    ) {
        return factory.get();
    }
}
