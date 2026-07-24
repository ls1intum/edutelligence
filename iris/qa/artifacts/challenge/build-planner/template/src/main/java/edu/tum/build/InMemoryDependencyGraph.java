package edu.tum.build;

import java.util.Set;

public final class InMemoryDependencyGraph implements DependencyGraph {
    public void addDependency(String module, String dependency) {
        // TODO
    }

    public Set<String> dependenciesOf(String module) {
        return Set.of();
    }

    public Set<String> dependentsOf(String module) {
        return Set.of();
    }

    public long revision() {
        return 0;
    }
}
