package edu.tum.build;

import java.util.Set;

public interface DependencyGraph {
    Set<String> dependenciesOf(String module);
    Set<String> dependentsOf(String module);
    long revision();
}
