# Supported Consistency Issues

## Definition of Consistency Issue

A **consistency issue** is an unintentional discrepancy between exercise artifacts (problem statement, template code, UML diagrams) where the same programming element is described or implemented differently, creating ambiguity about the intended design. This excludes intentional pedagogical gaps such as missing method implementations, incomplete constructors, or empty class bodies that students are expected to complete as part of the learning objective.

**Key Criteria:**

- **Unintentional**: Not a deliberate educational design choice
- **Same Element**: References the same conceptual programming entity
- **Different Representation**: Conflicting specifications across artifacts
- **Ambiguous Intent**: Students cannot determine the correct implementation approach

| **Category** | **Sub-Category** | **Definition** | **Example** | **Student Impact** |
|---|---|---|---|---|
| **STRUCTURAL** |  | Programming interface specifications differ between problem statement and template code | | Student cannot implement specification using provided template |
|  | METHOD_RETURN_TYPE_MISMATCH | Same method name has different return types | Problem: `int calculateTotal()` → Template: `void calculateTotal()` | Student cannot return required value from existing method |
|  | METHOD_PARAMETER_MISMATCH | Same method name has different parameter count, types, or order | Problem: `setDimensions(int width, int height)` → Template: `setDimensions(int size)` | Student cannot call method with required parameters |
|  | CONSTRUCTOR_PARAMETER_MISMATCH | Same class constructor has different parameter count, types, or order | Problem: `Engine(int power, Car car, int oil)` → Template: `Engine(int power, Car car)` | Student cannot instantiate object with required parameters |
|  | ATTRIBUTE_TYPE_MISMATCH | Same attribute name has different data types | Problem: `String name` → Template: `int name` | Student cannot store required data type in existing attribute |
|  | VISIBILITY_MISMATCH | Same method/attribute has different access modifiers | Problem: `public getBalance()` → Template: `private getBalance()` | Student cannot access method/attribute as specified |
| **SEMANTIC** |  | Same concept referenced with different names across artifacts | | Student cannot map problem statement requirements to template elements |
|  | IDENTIFIER_NAMING_INCONSISTENCY | Same conceptual entity has different names | Problem: `calculateTotal()` → Template: `getPrice()` | Student uncertain which template element implements specification requirement |
