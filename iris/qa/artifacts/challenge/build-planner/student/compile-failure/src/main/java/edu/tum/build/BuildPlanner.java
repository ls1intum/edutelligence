package edu.tum.build;

import java.util.List;
import java.util.Set;

public final class BuildPlanner {
    public List<String> plan(Set<String> changedModules) {
        return changedModules.stream().toList()
    }
}
