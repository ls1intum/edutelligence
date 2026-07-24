package edu.tum.build;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public final class BuildPlanner {
    private final DependencyGraph graph;
    private final BuildPlanCache cache;

    public BuildPlanner(DependencyGraph graph, BuildPlanCache cache) {
        this.graph = graph;
        this.cache = cache;
    }

    public List<String> plan(Set<String> changedModules) {
        return cache.getOrCompute(changedModules, graph.revision(), () -> {
            var queue = new ArrayDeque<>(changedModules);
            var seen = new HashSet<>(changedModules);
            while (!queue.isEmpty()) {
                for (var dependent : graph.dependentsOf(queue.remove())) {
                    if (seen.add(dependent)) {
                        queue.add(dependent);
                    }
                }
            }
            return new ArrayList<>(seen);
        });
    }
}
