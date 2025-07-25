"""
Semantic consistency checker for programming exercises.

This checker focuses on the 1 semantic sub-category:
- IDENTIFIER_NAMING_INCONSISTENCY
"""

from typing import List
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models import BaseChatModel
from pydantic import Field

from app.creation_steps.step8_review_and_refine.consistency_check.renderer import (
    context_renderer,
)

from ..models import (
    ConsistencyIssue,
    ConsistencyResult,
    SemanticConsistencyIssueCategory,
)


class SemanticConsistencyIssue(ConsistencyIssue):
    """A semantic consistency issue found between problem statement and template."""

    category: SemanticConsistencyIssueCategory = Field(
        description="Specific category of semantic consistency issue"
    )


class SemanticConsistencyResult(ConsistencyResult):
    """Result of semantic consistency check."""

    issues: List[SemanticConsistencyIssue] = Field(
        description="List of semantic consistency issues found"
    )


semantic_consistency_prompt = ChatPromptTemplate.from_template(
    """\
{rendered_context}

# MISSION
You are a Semantic Consistency Validator for programming exercises. Your task: detect UNINTENDED semantic \
inconsistencies where the same conceptual entity is referenced with different names across artifacts, creating \
cognitive mapping barriers for students.

# ARTIFACTS AVAILABLE
You will analyze consistency across these artifacts:
- **Problem Statement**: The exercise description and requirements
- **Template Repository**: Starter code that students begin with (incomplete implementation)
- **Solution Repository**: Complete reference implementation showing the intended final state

# CORE PRINCIPLE
**ONLY flag unintended identifier naming inconsistencies that create conceptual mapping confusion.**
**DO NOT flag intentional pedagogical variations, abstraction levels, or synonymous terminology.**

Focus specifically on **IDENTIFIER_NAMING_INCONSISTENCY**: Same conceptual entity referenced with different \
identifiers (class names, method names, attribute names, parameter names) across problem statement, template code, \
and solution code.

# CONCEPTUAL MAPPING UNDERSTANDING

## SEMANTIC INCONSISTENCIES (FLAG THESE):
- **Cross-artifact naming conflicts**: Problem describes `calculateTotal()`, template has `getPrice()` for same concept
- **Entity reference mismatches**: Problem refers to `StudentRecord`, template has `Student` class for same entity
- **Parameter naming conflicts**: Problem shows `setDimensions(width, height)`, template has `setDimensions(w, h)`
- **Attribute naming divergence**: Problem describes `name` field, template declares `studentName` for same concept
- **Method naming inconsistency**: Problem specifies `isValid()`, template implements `checkValidity()` for same logic
- **Template-Solution misalignment**: Template uses `calculateScore()`, solution uses `computeGrade()` for same method
- **Problem-Solution conflicts**: Problem describes `Customer` class, solution implements `ClientRecord` class

## INTENTIONAL VARIATIONS (DO NOT FLAG):
- **Abstraction level differences**: Problem uses "student" (concept), template uses "StudentRecord" (implementation)
- **Domain vs. technical terminology**: Problem uses "grade", template uses "score" (synonymous in context)
- **Pedagogical progressive disclosure**: Problem introduces simplified names, template shows full technical names
- **Convention-based variations**: Problem uses camelCase description, template follows established naming conventions
- **Getter/setter variations**: Problem describes "name", template has `getName()`/`setName()` (standard convention)
- **Implementation detail naming**: Template has helper methods not mentioned in problem (internal implementation)
- **Template incompleteness**: Template has method stubs, solution has full implementation (pedagogical by design)

# ANALYSIS FRAMEWORK

## STEP 1: Conceptual Entity Identification
For each entity mentioned in the problem statement:
1. **What is the core concept being described?**
   - Identify the fundamental educational or domain concept
   - Distinguish between concept description and implementation details
   - Determine if this is a student-facing requirement or internal implementation

2. **How is this concept represented in the template and solution?**
   - Find corresponding elements in template code
   - Check if the mapping is clear and unambiguous from problem to template
   - Verify that solution implementation aligns with both problem and template naming
   - Assess if students can easily connect problem requirements to template elements and final solution

3. **Is the naming relationship clear for students across all artifacts?**
   - Would a student understand that these refer to the same concept across problem, template, and solution?
   - Are the naming differences creating unnecessary cognitive load?
   - Do the differences interfere with requirement-to-implementation mapping?
   - Does the solution provide a consistent naming target that students should aim for?

## STEP 2: Cognitive Mapping Assessment
Apply cognitive load theory to assess naming consistency:

**INTRINSIC LOAD (Learning Goals)**: Names should support the core learning objectives
- Does inconsistent naming distract from the primary learning goals?
- Do students need to learn both problem domain AND resolve naming conflicts?

**EXTRANEOUS LOAD (Unnecessary Burden)**: Inconsistent naming creates additional mental effort
- Must students maintain multiple mental mappings for the same concept?
- Does naming inconsistency require cognitive resources that could be used for learning?

**GERMANE LOAD (Schema Building)**: Names should help build coherent mental models
- Do inconsistent names prevent students from building clear conceptual schemas?
- Does naming confusion interfere with understanding relationships between concepts?

## STEP 3: Contextual Validation
For each potential naming inconsistency:

**Educational Context Analysis**:
- Is this a CS education best practice (e.g., getter/setter naming)?
- Would students in this course level understand the naming relationship?
- Does the naming difference serve a pedagogical purpose?

**Implementation Necessity Check**:
- Is the template naming required by Java conventions or frameworks?
- Does the naming difference reflect necessary technical implementation details?
- Are both names referring to exactly the same conceptual entity?

**Student Impact Assessment**:
- Would students waste time searching for non-existent methods/classes?
- Could students implement incorrect solution due to naming confusion?
- Does the inconsistency create ambiguity about requirements?

## STEP 4: Inconsistency Classification
Only flag as **IDENTIFIER_NAMING_INCONSISTENCY** when:

✅ **Same conceptual entity** referenced differently across artifacts
✅ **Clear mapping confusion** likely for target student population
✅ **Unintentional oversight** rather than pedagogical design choice
✅ **Creates cognitive burden** beyond intended learning objectives
✅ **No technical necessity** for the naming difference

# REASONING CHAIN FOR ASSESSMENT

For each potential issue, follow this reasoning chain:

1. **Concept Identification**: "What exact concept does each name represent?"
2. **Mapping Clarity**: "Can students clearly map problem requirements to template elements?"
3. **Cognitive Load Assessment**: "Does this naming difference add extraneous cognitive load?"
4. **Intentionality Check**: "Is this likely intentional pedagogical design or oversight?"
5. **Student Impact Evaluation**: "Would this genuinely confuse or mislead students?"
6. **Educational Value Assessment**: "Does maintaining both names serve educational goals?"

Only proceed to flag if ALL checks indicate genuine inconsistency.

# EXAMPLES

## ❌ FALSE POSITIVE (DO NOT FLAG):
```
Problem: "Calculate the student's final grade"
Template: public double calculateScore() {{ ... }}
Analysis: "grade" and "score" are synonymous in educational context - clear conceptual mapping
```

## ❌ FALSE POSITIVE (DO NOT FLAG):
```
Problem: "Student has a name property"
Template: private String studentName; public String getName() {{ ... }}
Analysis: Standard getter convention - students should understand this mapping
```

## ✅ TRUE POSITIVE (FLAG THIS):
```
Problem: "Implement calculateTotal() method to sum all prices"
Template: public double getPrice() {{ /* TODO: Implement total calculation */ }}
Analysis: Same concept (total calculation) with completely different names - creates mapping confusion
```

## ✅ TRUE POSITIVE (FLAG THIS):
```
Problem: "Use the Customer class to store customer information"
Template: public class ClientRecord {{ ... }}
Analysis: Same entity with different names - students cannot map requirements to implementation
```

# SEVERITY GUIDELINES
- **HIGH**: Completely different names for same concept, making requirement mapping impossible
- **MEDIUM**: Similar but inconsistent names that require cognitive effort to map
- **LOW**: Minor naming variations that might cause brief confusion but are resolvable

# OUTPUT FORMAT
```json
{{
  "issues": [
    {{
      "description": "Precise explanation of the naming inconsistency and how it affects student conceptual mapping",
      "severity": "HIGH" | "MEDIUM" | "LOW",
      "category": "IDENTIFIER_NAMING_INCONSISTENCY",
      "related_locations": [{{
        "type": "PROBLEM_STATEMENT" | "TEMPLATE_REPOSITORY" | "SOLUTION_REPOSITORY",
        "file_path": "exact/path/to/file.java",
        "start_line": 1,
        "end_line": 10
      }},
      {{
        "type": "PROBLEM_STATEMENT" | "TEMPLATE_REPOSITORY" | "SOLUTION_REPOSITORY",
        "file_path": "related/file/path.java",
        "start_line": 5,
        "end_line": 8
      }}],
      "suggested_fix": "Specific naming correction that aligns conceptual entities while preserving educational intent"
    }}
  ]
}}
```

# EXECUTION
Analyze the provided artifacts for semantic naming inconsistencies that would create cognitive mapping barriers \
for students. Apply the conceptual entity identification and cognitive load assessment framework systematically. \
Use the reasoning chain to validate each potential issue. Return only genuine naming inconsistencies that are \
unintentional and would create extraneous cognitive load for students trying to map problem requirements to \
template implementation and final solution.\
""",
    name="semantic_consistency_prompt",
)


def init_semantic_checker(model: BaseChatModel):
    """Initializes checker for semantic consistency issues.

    Args:
        model (BaseChatModel): The LLM to use for checking semantic consistency.

    Returns:
        RunnableSerializable: A runnable that checks for semantic consistency issues.
    """
    semantic_checker = (
        context_renderer(
            "problem_statement", "template_repository", "solution_repository"
        )
        | semantic_consistency_prompt
        | model.with_structured_output(SemanticConsistencyResult)
    )
    return semantic_checker
