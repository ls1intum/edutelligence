# Supported Consistency Issues

## Definition of Consistency Issue

A **consistency issue** is an unintentional violation of **instructional coherence** within or across exercise artifacts that creates **extraneous cognitive load** by presenting contradictory information about the same educational element. Drawing from Mayer's Coherence Principle and Biggs' Constructive Alignment theory, consistency issues occur when the **intentional pedagogical design** is disrupted by conflicting representations that force learners to engage in unnecessary cognitive reconciliation rather than focusing on the intended learning objectives.

**Theoretical Foundation:**

- **Coherence Principle** (Mayer): Learning is optimized when extraneous material is excluded; consistency issues introduce unintended extraneous elements
- **Constructive Alignment** (Biggs): All instructional components should align toward learning objectives; inconsistencies break this alignment
- **Cognitive Load Theory** (Sweller): Learners have limited working memory; contradictory information creates unnecessary cognitive burden

**Distinguishing Criteria:**

- **Unintentional Discrepancy**: Artifact conflicts not deliberately designed for pedagogical purposes
- **Same Educational Element**: Multiple representations of the same conceptual entity (class, method, attribute, relationship, constraint)
- **Contradictory Specification**: Conflicting information that cannot be simultaneously satisfied
- **Extraneous Cognitive Demand**: Forces learners to resolve conflicts rather than engage with intended learning content
- **Pedagogical Disruption**: Interferes with the constructive alignment between learning objectives, activities, and assessment

**Excluded from Definition:**

- **Intentional Scaffolding**: Deliberately incomplete implementations for student completion
- **Progressive Disclosure**: Intentionally simplified initial representations that are later expanded
- **Pedagogical Abstraction**: Deliberately simplified models for educational purposes

## Consistency Issue Categories

### **STRUCTURAL**

Inconsistencies in formal structure, interfaces, or specifications where precise rules govern correctness. These issues create implementation barriers because conflicting structural elements cannot be simultaneously satisfied.

### **SEMANTIC**

Inconsistencies in conceptual meaning or terminology where the same knowledge is represented differently across artifacts. These issues create cognitive mapping barriers because learners cannot establish clear connections between equivalent concepts.

### **ASSESSMENT**

Inconsistencies between instructional content and evaluation criteria, including misaligned learning objectives, assessment methods, or performance standards. These issues create evaluation barriers where assessment does not measure what was taught or intended.

### **TEMPORAL**

Inconsistencies in sequencing, pacing, or prerequisite relationships across instructional materials. These issues create learning progression barriers where the order or timing of content presentation conflicts with pedagogical design or cognitive development principles.

### **SCOPE**

Inconsistencies in the breadth, depth, or coverage of content across artifacts. These issues create learning boundary barriers where different materials present conflicting information about what should be learned, to what level, or in what detail.

| **Category** | **Sub-Category** | **Definition** | **Example** | **Student Impact** |
|---|---|---|---|---|
| **STRUCTURAL** |  | Formal interface specifications differ between problem statement and template code | | Student cannot implement specification using provided template |
|  | METHOD_RETURN_TYPE_MISMATCH | Same method name has different return types | Problem: `int calculateTotal()` → Template: `void calculateTotal()` | Student cannot return required value from existing method |
|  | METHOD_PARAMETER_MISMATCH | Same method name has different parameter count, types, or order | Problem: `setDimensions(int width, int height)` → Template: `setDimensions(int size)` | Student cannot call method with required parameters |
|  | CONSTRUCTOR_PARAMETER_MISMATCH | Same class constructor has different parameter count, types, or order | Problem: `Engine(int power, Car car, int oil)` → Template: `Engine(int power, Car car)` | Student cannot instantiate object with required parameters |
|  | ATTRIBUTE_TYPE_MISMATCH | Same attribute name has different data types | Problem: `String name` → Template: `int name` | Student cannot store required data type in existing attribute |
|  | VISIBILITY_MISMATCH | Same method/attribute has different access modifiers | Problem: `public getBalance()` → Template: `private getBalance()` | Student cannot access method/attribute as specified |
| **SEMANTIC** |  | Same concept referenced with different names across artifacts | | Student cannot map problem statement requirements to template elements |
|  | IDENTIFIER_NAMING_INCONSISTENCY | Same conceptual entity has different names | Problem: `calculateTotal()` → Template: `getPrice()` | Student uncertain which template element implements specification requirement |
