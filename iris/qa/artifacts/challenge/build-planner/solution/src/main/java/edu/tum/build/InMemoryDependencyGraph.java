package edu.tum.build;

import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

public final class InMemoryDependencyGraph implements DependencyGraph {
    private final Map<String, Set<String>> dependencies = new HashMap<>();
    private final Map<String, Set<String>> dependents = new HashMap<>();
    private long revision;

    public void addDependency(String module, String dependency) {
        if (dependencies.computeIfAbsent(module, ignored -> new LinkedHashSet<>())
                .add(dependency)) {
            dependents.computeIfAbsent(dependency, ignored -> new LinkedHashSet<>())
                .add(module);
            revision++;
        }
    }

    public Set<String> dependenciesOf(String module) {
        return dependencies.getOrDefault(module, Set.of());
    }

    public Set<String> dependentsOf(String module) {
        return dependents.getOrDefault(module, Set.of());
    }

    public long revision() {
        return revision;
    }
}
