from enum import Enum
from typing import List
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

# Models to reuse for structured output
from .models import ConsistencyIssueSeverity


structural_consistency_prompt = ChatPromptTemplate.from_template(
    """\
{rendered_context}

# MISSION
You are a Structural Consistency Validator for programming exercises. Your task: detect UNINTENDED structural \
inconsistencies that would confuse students or prevent them from implementing the intended design. Focus on ensuring \
coherence between what the problem statement describes and what the template code provides.

# CORE PRINCIPLE
**ONLY flag unintentional structural inconsistencies that create student confusion or implementation barriers.**
**DO NOT flag intentional pedagogical gaps (missing method bodies, incomplete implementations, etc.)**

This includes:
- **Cross-artifact inconsistencies**: Problem statement describes one structure, template implements another
- **Inner-artifact inconsistencies**: Contradictions within the problem statement or template itself
- **Design implementation barriers**: Template structure prevents students from following the specified design

# PEDAGOGICAL VS. STRUCTURAL UNDERSTANDING

## PEDAGOGICAL GAPS (DO NOT FLAG):
- Missing method bodies in template classes (students implement these)
- Incomplete constructor implementations
- Abstract methods without implementation (by design)
- Missing private helper methods students should write
- Incomplete exception handling in method stubs
- Missing validation logic in setter methods
- Empty method stubs with TODO comments

## STRUCTURAL INCONSISTENCIES (FLAG THESE):
- **Cross-artifact conflicts**: Problem describes inheritance, template has standalone classes
- **Design contradictions**: Problem states interface implementation, template has conflicting signatures
- **Missing structural foundation**: Problem references classes/enums that don't exist in template
- **Inner-artifact contradictions**: Problem statement describes same element differently in multiple places
- **Template self-contradictions**: Template code has conflicting declarations or imports
- **Type/signature mismatches**: Return types, parameters, or visibility that prevent intended design

# ANALYSIS FRAMEWORK

## STEP 1: Educational Context Analysis
Before identifying issues, determine:
- What design is the problem statement trying to teach?
- Does the template structure support this design or contradict it?
- Are missing elements intentional learning gaps or structural oversights?
- Would students be confused by conflicting information between artifacts?

## STEP 2: Consistency Validation
Check for these specific inconsistencies:

**METHOD_SIGNATURE_MISMATCH**: Conflicting signatures between problem description and template
- Example: Problem describes `getArea()` returns `double`, template declares `int getArea()`
- Not flagged: Missing method body in template method

**CONSTRUCTOR_SIGNATURE_MISMATCH**: Constructor conflicts between specification and template
- Example: Problem requires `Person(String name)`, template only has `Person()`
- Not flagged: Empty constructor body in template

**INTERFACE_IMPLEMENTATION_CONFLICT**: Signature mismatches preventing interface implementation
- Example: Problem shows interface with `calculate(int x)`, template class has `calculate(double x)`
- Not flagged: Missing implementation of interface method (students implement)

**TYPE_DECLARATION_CONFLICT**: Data type inconsistencies across or within artifacts
- Example: Problem states `List<String> names`, template declares `String[] names`
- Example: Problem statement describes same field as both `int` and `String` in different sections
- Not flagged: Uninitialized fields in template

**INHERITANCE_HIERARCHY_MISMATCH**: Class relationship conflicts between description and template
- Example: Problem describes `Student extends Person`, template has no extension
- Example: Problem UML shows inheritance, but text description contradicts it
- Not flagged: Missing call to `super()` in constructor body

**PACKAGE_STRUCTURE_MISMATCH**: Import/package inconsistencies or errors
- Example: Template imports non-existent package
- Example: Problem references classes in wrong package structure
- Not flagged: Unused imports in template

**MISSING_REQUIRED_ELEMENT**: Essential structural components absent from template
- Example: Problem references `StatusEnum`, no such enum exists in template
- Example: Problem describes interface `Drawable`, but it's missing from template
- Not flagged: Missing concrete method implementations

## STEP 3: Self-Verification
For each potential issue, ask:
1. Is this a structural inconsistency or intentional pedagogical design?
2. Would this confuse students about what they're supposed to implement?
3. Does this prevent students from following the intended design pattern?
4. Is this an unintentional oversight rather than a learning exercise?

Only flag issues where students would be genuinely confused or blocked from implementing the intended solution.

# EXAMPLES

## ❌ FALSE POSITIVE (DO NOT FLAG):
```
Problem: "Implement the calculateGrade() method in Student class"
Template: public void calculateGrade() {{ /* TODO: Implement */ }}
Analysis: This is intentional - students should implement the method body
```

## ✅ TRUE POSITIVE (FLAG THIS):
```
Problem: "Student class extends Person with calculateGrade() method"
Template: public class Student {{ ... }} // no extends Person
Analysis: Cross-artifact inconsistency - students can't implement inheritance design
```

## ✅ INNER-ARTIFACT INCONSISTENCY (FLAG THIS):
```
Problem statement: "Vehicle has method getSpeed() returning int" ... later "getSpeed() returns double"
Analysis: Problem contradicts itself about return type
```

# SEVERITY GUIDELINES
- **HIGH**: Creates major confusion or makes core design impossible to implement
- **MEDIUM**: Creates significant confusion or requires workarounds to implement intended design
- **LOW**: Minor inconsistencies that might cause brief confusion but are easily resolved

# OUTPUT FORMAT
```json
{{
  "issues": [
    {{
      "description": "Precise explanation of the inconsistency and how it affects student understanding/implementation",
      "severity": "HIGH" | "MEDIUM" | "LOW",
      "category": "METHOD_SIGNATURE_MISMATCH" | "CONSTRUCTOR_SIGNATURE_MISMATCH" | "INTERFACE_IMPLEMENTATION_CONFLICT" \
| "TYPE_DECLARATION_CONFLICT" | "INHERITANCE_HIERARCHY_MISMATCH" | "PACKAGE_STRUCTURE_MISMATCH" | \
"MISSING_REQUIRED_ELEMENT",
      "primary_location": {{
        "type": "PROBLEM_STATEMENT" | "TEMPLATE_REPOSITORY",
        "file_path": "exact/path/to/file.java",
        "start_line": 1,
        "end_line": 10
      }},
      "related_locations": [{{
        "type": "PROBLEM_STATEMENT" | "TEMPLATE_REPOSITORY",
        "file_path": "related/file/path.java",
        "start_line": 5,
        "end_line": 8
      }}],
      "suggested_fix": "Specific correction that resolves the inconsistency while preserving educational intent"
    }}
  ]
}}
```

# EXECUTION
Analyze the provided artifacts for structural inconsistencies that would confuse students or prevent them from \
implementing the intended design. Focus on cross-artifact contradictions (problem vs template) and inner-artifact \
contradictions (within problem statement or template). Apply the pedagogical vs. structural distinction rigorously. \
Return only genuine inconsistencies that are unintentional and would hinder student success.\
""",
    name="structural_consistency_prompt",
)


class ArtifactType(str, Enum):
    PROBLEM_STATEMENT = "PROBLEM_STATEMENT"
    TEMPLATE_REPOSITORY = "TEMPLATE_REPOSITORY"


class StructuralConsistencyIssueCategory(str, Enum):
    # Method return type, parameters, or visibility differs between artifacts
    METHOD_SIGNATURE_MISMATCH = "METHOD_SIGNATURE_MISMATCH"

    # Constructor parameters differ between specification and template
    CONSTRUCTOR_SIGNATURE_MISMATCH = "CONSTRUCTOR_SIGNATURE_MISMATCH"

    # Required interface cannot be implemented as specified
    INTERFACE_IMPLEMENTATION_CONFLICT = "INTERFACE_IMPLEMENTATION_CONFLICT"

    # Data types inconsistent across artifacts
    TYPE_DECLARATION_CONFLICT = "TYPE_DECLARATION_CONFLICT"

    # Extends/implements relationships differ between UML and template
    INHERITANCE_HIERARCHY_MISMATCH = "INHERITANCE_HIERARCHY_MISMATCH"

    # Import/package organization prevents compilation
    PACKAGE_STRUCTURE_MISMATCH = "PACKAGE_STRUCTURE_MISMATCH"

    # Essential class/method/attribute missing from template
    MISSING_REQUIRED_ELEMENT = "MISSING_REQUIRED_ELEMENT"


class ArtifactLocation(BaseModel):
    type: ArtifactType = Field(description="Type of artifact")
    file_path: str = Field(description="Path to file, empty for problem statement")
    start_line: int = Field(description="Start line number (1-based)")
    end_line: int = Field(description="End line number (1-based)")


# Do not use this directly, use subclasses instead
class ConsistencyIssue(BaseModel):
    description: str = Field(description="Clear explanation of the signature mismatch")
    severity: ConsistencyIssueSeverity = Field(
        description="Student impact severity level"
    )
    category: str = Field(description="Specific category of consistency issue")
    primary_location: ArtifactLocation = Field(
        description="Primary location where issue was detected"
    )
    related_locations: List[ArtifactLocation] = Field(
        description="Related locations across artifacts"
    )
    suggested_fix: str = Field(
        description="Actionable correction to resolve the mismatch"
    )


class StructuralConsistencyIssue(ConsistencyIssue):
    """A signature consistency issue found between problem statement and template."""

    description: str = Field(description="Clear explanation of the signature mismatch")
    severity: ConsistencyIssueSeverity = Field(
        description="Student impact severity level"
    )
    category: StructuralConsistencyIssueCategory = Field(
        description="Specific category of structural consistency issue"
    )
    primary_location: ArtifactLocation = Field(
        description="Primary location where issue was detected"
    )
    related_locations: List[ArtifactLocation] = Field(
        description="Related locations across artifacts"
    )
    suggested_fix: str = Field(
        description="Actionable correction to resolve the mismatch"
    )


# Do not use this directly, use subclasses instead
class ConsistencyResult(BaseModel):
    """Result of consistency issue analysis."""

    issues: List[ConsistencyIssue] = Field(
        description="List of detected consistency issues"
    )


class StructuralConsistencyResult(ConsistencyResult):
    """Result of structural consistency issue analysis."""

    issues: List[StructuralConsistencyIssue] = Field(
        description="List of detected structural consistency issues"
    )
