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
                var current = queue.remove();
                for (var dependency : graph.dependenciesOf(current)) {
                    if (seen.add(dependency)) {
                        queue.add(dependency);
                    }
                }
            }
            return new ArrayList<>(seen);
        });
    }
}
