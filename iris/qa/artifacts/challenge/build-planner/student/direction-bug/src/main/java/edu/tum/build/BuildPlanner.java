package edu.tum.build;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public final class BuildPlanner {
    private final DependencyGraph graph;

    public BuildPlanner(DependencyGraph graph) {
        this.graph = graph;
    }

    public List<String> plan(Set<String> changedModules) {
        var queue = new ArrayDeque<>(changedModules);
        var seen = new HashSet<>(changedModules);
        while (!queue.isEmpty()) {
            for (var dependency : graph.dependenciesOf(queue.remove())) {
                if (seen.add(dependency)) {
                    queue.add(dependency);
                }
            }
        }
        return new ArrayList<>(seen);
    }
}
