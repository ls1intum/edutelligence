package edu.tum.build;

import static org.junit.jupiter.api.Assertions.assertEquals;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.Test;

class BuildPlannerTest {
    @Test
    void rebuildsTransitiveDependents() {
        var graph = new InMemoryDependencyGraph();
        graph.addDependency("api", "core");
        graph.addDependency("web", "api");
        var planner = new BuildPlanner(graph, new BuildPlanCache());
        assertEquals(Set.of("core", "api", "web"), Set.copyOf(planner.plan(Set.of("core"))));
    }

    @Test
    void invalidatesPlansWhenTheGraphChanges() {
        var graph = new InMemoryDependencyGraph();
        graph.addDependency("api", "core");
        graph.addDependency("web", "api");
        var planner = new BuildPlanner(graph, new BuildPlanCache());
        planner.plan(Set.of("core"));
        graph.addDependency("cli", "api");
        assertEquals(
            Set.of("core", "api", "web", "cli"),
            Set.copyOf(planner.plan(Set.of("core")))
        );
    }
}
