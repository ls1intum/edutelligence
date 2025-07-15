# Programming Exercise Consistency Taxonomy

| **Category** | **Sub-Category** | **Definition** | **Example** | **Student Impact** |
|---|---|---|---|---|
| **STRUCTURAL** |  | Required interface/structure differs between artifacts, preventing technical implementation | | Cannot compile or implement solution |
|  | METHOD_SIGNATURE_MISMATCH | Method return type, parameters, or visibility differs between artifacts | Problem: `int calculateTotal()` → Template: `void calculateTotal()` | Cannot implement required functionality |
|  | CONSTRUCTOR_SIGNATURE_MISMATCH | Constructor parameters differ between specification and template | Problem: `Engine(power, car, oil)` → Template: `Engine(power, car)` | Cannot instantiate objects as specified |
|  | INTERFACE_IMPLEMENTATION_CONFLICT | Required interface cannot be implemented as specified | UML: implements Drawable → Template: no interface | Cannot fulfill contract requirements |
|  | TYPE_DECLARATION_CONFLICT | Data types inconsistent across artifacts | UML: String name → Template: int name | Cannot establish proper data structures |
|  | INHERITANCE_HIERARCHY_MISMATCH | Extends/implements relationships differ between UML and template | UML: extends Vehicle → Template: standalone class | Cannot establish proper class relationships |
|  | PACKAGE_STRUCTURE_MISMATCH | Import/package organization prevents compilation | Problem: `de.tum.cit.ase` → Template: `de.tum.in.ase.eist` | Cannot resolve dependencies |
|  | MISSING_REQUIRED_ELEMENT | Essential class/method/attribute missing from template | Problem: "implement getDuration()" → Template: method missing | Cannot complete required implementation |
| **SEMANTIC** |  | Same concept represented differently across artifacts, creating cognitive confusion | | Gets confused about what to implement |
|  | NAMING_INCONSISTENCY | Same concept has different names across artifacts | Problem: "calculateTotal" → Template: `getTotalCost()` | Terminology confusion blocks concept mapping |
|  | UML_TEXT_DEVIATION | UML diagram structure doesn't match textual specification | UML: composition → Text: "uses inheritance" | Visual-textual mismatch disrupts understanding |
|  | EXAMPLE_CONTRADICTION | Provided examples contradict stated requirements | Problem: "use ArrayList" → Example: uses HashMap | Conflicting models impede pattern recognition |
|  | SPECIFICATION_AMBIGUITY | Multiple valid interpretations possible from unclear wording | "implement calculateTotal" (algorithm unclear) | Multiple interpretations prevent focused learning |
|  | CONSTRAINT_VIOLATION | Template violates explicit constraints from problem statement | Problem: "use recursion" → Template: iterative skeleton | Implementation guidance contradicts requirements |
|  | REQUIREMENT_GAP | Specification missing from implementation guidance | Problem: "validate input" → Template: no validation hints | Missing guidance for required functionality |
| **ASSESSMENT** |  | Tests/evaluation criteria don't match instructional objectives | | Thinks they're correct but fails tests |
|  | TEST_OBJECTIVE_MISMATCH | Tests measure different cognitive skills than learning objectives | Objective: Design algorithms → Tests: Syntax checking | Tests different cognitive level than intended |
|  | TEST_COVERAGE_INCOMPLETE | Missing tests for specified functionality | Objective: Error handling → Tests: Happy path only | Critical skills go unevaluated |
|  | TEST_DATA_INCONSISTENT | Test data format/values differ from problem examples | Problem: Positive integers → Tests: Negative/zero | Assessment context differs from learning context |
|  | GRADING_CRITERIA_CONFLICT | Assessment emphasizes different aspects than instruction | Instructions: Efficiency → Grading: Correctness only | Mixed signals about valued skills |
|  | TEST_METHOD_NAMING_CONFLICT | Required test method names differ between specification sources | Problem: "testCalculateTotal" → Tests: "testTotalCalculation" | Cannot meet assessment requirements |
| **PEDAGOGICAL** |  | Exercise violates learning objective alignment and pedagogical design principles | | Undermines learning progression and skill development |
|  | COGNITIVE_LEVEL_MISMATCH | Exercise cognitive demands don't match stated learning objectives | Objective: "Apply OOP principles" → Exercise: memorize syntax | Bloom's taxonomy level confusion (Apply → Remember) |
|  | SCAFFOLDING_DISCONTINUITY | Support provided doesn't match cognitive demands of learning objectives | Complex design pattern → No architectural guidance | Zone of Proximal Development violation |
|  | PREREQUISITE_ASSUMPTION_VIOLATION | Exercise assumes knowledge/skills not established in curriculum sequence | Week 3 exercise requires lambdas (taught Week 8) | Curriculum sequencing violation |
|  | LEARNING_OBJECTIVE_CONTRADICTION | Exercise requirements contradict stated pedagogical goals | Objective: "Design clean code" → Template: promotes anti-patterns | Skill transfer impediment |
|  | COMPLEXITY_PROGRESSION_VIOLATION | Difficulty level inappropriate for curriculum sequence | Basic loops course → Advanced algorithm optimization | SOLO taxonomy level jump |
|  | SKILL_TRANSFER_IMPEDIMENT | Exercise design inhibits real-world application of learned skills | Artificial constraints that don't exist in practice | Transfer theory violation |
