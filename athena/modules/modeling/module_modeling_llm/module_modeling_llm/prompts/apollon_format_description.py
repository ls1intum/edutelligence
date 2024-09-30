apollon_format_description = """
### Apollon Format Documentation

The Apollon format is a textual representation of UML diagrams, designed to be easily understood and interpreted by both humans and language models (LLMs). It resembles the Mermaid format and allows for the description of various UML diagram types with a structured syntax.

#### Diagram Types

The Apollon format supports many different UML diagram types, including:

- **ClassDiagram**
- **ObjectDiagram**
- **ActivityDiagram**
- **UseCaseDiagram**
- **CommunicationDiagram**
- **ComponentDiagram**
- **DeploymentDiagram**
- **PetriNet**
- **ReachabilityGraph**
- **SyntaxTree**
- **Flowchart**
- **BPMN**

#### Format Structure

The Apollon format is organized into three main categories:

1. **Elements**: The basic components of the diagram (e.g., classes, objects, activities).
2. **Relations**: Connections between elements that depict relationships or interactions.
3. **Nested Elements**: Hierarchical structures or containment relationships.

##### General Structure

```apollon
UML Diagram Type: <nameOfUMLDiagramType>

Elements:
[ElementType] <elementName>

Relations:
R<number>: <element1> (<relationType>) <relationTypeArrowRepresentation> <element2>

Nested Elements:
<ElementOwner>: [<elementName>]
```

##### Naming

When there are elements in the original diagram with the same name, the Apollon format appends a unique suffix to each duplicate name to ensure clarity and avoid ambiguity. This suffix can be identified by the `#` symbol followed by an uppercase letter.

When there are elements in the original diagram with no name, the Apollon format assignes them uppercase letters for the name. These can be identified by the `##` symbol followed by an uppercase letter.

##### Detailed Breakdown

- **Elements**: 
  - Defined by their type and name. Optionally, attributes and methods can be listed.
  - Example:
    ```apollon
    [Class] User {
        attributes:
            name
            email
        methods:
            login()
            logout()
    }
    ```

- **Relations**: 
  - Relations define the connections between two elements, capturing the nature of their interaction. Each relation can include optional attributes such as labels, roles, multiplicities, and messages to provide more detailed information.
  - The `R<number>` syntax serves as a unique identifier for each relation, ensuring that it can be easily referenced elsewhere
  - Example (Basic):
    ```apollon
    R1: User --> Order
  - Example (With label):
    ```apollon
    R1: User (Association) --> Order: places
    ```
  - Example (With label, roles and multiplicities):
    ```apollon
    R2: User (Association) --> Order {
        label: places
        User: {
            role: customer
            multiplicity: 1
        }
        Order: {
            role: order
            multiplicity: *
        }
        messages: [
            { name: "Place Order", to_direction: Order }
        ]
    }
    ```

- **Nested Elements**: 
  - Used to represent elements contained within other elements.
  - Example:
    ```apollon
    Package: [User, Order, Product]
    ```

"""