from athena.schemas.grading_criterion import (
    GradingCriterion,
    StructuredGradingInstruction,
)

# Grading criteria for e-commerce system
ECOMMERCE_GRADING_CRITERIA = [
    GradingCriterion(
        id=1,
        title="User has email attribute",
        structured_grading_instructions=[
            StructuredGradingInstruction(
                id=1,
                credits=2.0,
                grading_scale="Good",
                instruction_description="User class must have an email attribute.",
                feedback="User class has the required email attribute.",
                usage_count=0,
            )
        ],
    ),
    GradingCriterion(
        id=2,
        title="Order-Product Association",
        structured_grading_instructions=[
            StructuredGradingInstruction(
                id=2,
                credits=2.0,
                grading_scale="Good",
                instruction_description="Order and Product must be associated (association).",
                feedback="Order and Product are correctly associated.",
                usage_count=0,
            )
        ],
    ),
    GradingCriterion(
        id=3,
        title="Cart-Product Composition",
        structured_grading_instructions=[
            StructuredGradingInstruction(
                id=3,
                credits=2.0,
                grading_scale="Good",
                instruction_description="Cart must have a composition relationship with Product.",
                feedback="Cart and Product are correctly in a composition relationship.",
                usage_count=0,
            )
        ],
    ),
    GradingCriterion(
        id=4,
        title="User-Address Aggregation",
        structured_grading_instructions=[
            StructuredGradingInstruction(
                id=4,
                credits=2.0,
                grading_scale="Good",
                instruction_description="User must have an aggregation relationship with Address.",
                feedback="User and Address are correctly in an aggregation relationship.",
                usage_count=0,
            )
        ],
    ),
    GradingCriterion(
        id=5,
        title="Order inherits from Cart",
        structured_grading_instructions=[
            StructuredGradingInstruction(
                id=5,
                credits=2.0,
                grading_scale="Good",
                instruction_description="Order must inherit from Cart.",
                feedback="Order correctly inherits from Cart.",
                usage_count=0,
            )
        ],
    ),
]

# Problem statement and grading instructions
ECOMMERCE_PROBLEM_STATEMENT = (
    "Design a UML class diagram for a simple e-commerce system. "
    "The system should allow users to place orders for products. "
    "Each user should have a unique email address for identification. "
    "A cart collects products before an order is placed. "
    "Model the relationships between User, Order, Product, Cart, and Address. "
    "Include relevant attributes and relationships to reflect a real-world scenario."
)

ECOMMERCE_GRADING_INSTRUCTIONS = (
    "1. The User class must have an email attribute.\n"
    "2. There must be an association between Order and Product (an order contains products).\n"
    "3. The Cart class must have a composition relationship with Product (a cart is composed of products).\n"
    "4. The User class must have an aggregation relationship with Address (a user can have multiple addresses).\n"
    "5. The Order class must inherit from Cart (an order is a finalized cart).\n"
)

# Example solution and submission JSON
ECOMMERCE_EXAMPLE_SOLUTION = """
{
    "type": "ClassDiagram",
    "elements": {
        "1": {"id": "1", "type": "Class", "name": "User", "attributes": ["6"], "methods": []},
        "2": {"id": "2", "type": "Class", "name": "Order", "attributes": [], "methods": []},
        "3": {"id": "3", "type": "Class", "name": "Product", "attributes": [], "methods": []},
        "4": {"id": "4", "type": "Class", "name": "Cart", "attributes": [], "methods": []},
        "5": {"id": "5", "type": "Class", "name": "Address", "attributes": [], "methods": []},
        "6": {"id": "6", "type": "Attribute", "name": "email"}
    },
    "relationships": {
        "r1": {"id": "r1", "type": "Association", "source": {"element": "2"}, "target": {"element": "3"}},
        "r2": {"id": "r2", "type": "Composition", "source": {"element": "4"}, "target": {"element": "3"}},
        "r3": {"id": "r3", "type": "Aggregation", "source": {"element": "1"}, "target": {"element": "5"}},
        "r4": {"id": "r4", "type": "Inheritance", "source": {"element": "2"}, "target": {"element": "4"}}
    }
}
"""

ECOMMERCE_SUBMISSION = """
{
    "type": "ClassDiagram",
    "elements": {
        "1": {"id": "1", "type": "Class", "name": "User", "attributes": [], "methods": []},
        "2": {"id": "2", "type": "Class", "name": "Order", "attributes": [], "methods": []},
        "3": {"id": "3", "type": "Class", "name": "Product", "attributes": [], "methods": []},
        "4": {"id": "4", "type": "Class", "name": "Cart", "attributes": [], "methods": []},
        "5": {"id": "5", "type": "Class", "name": "Address", "attributes": [], "methods": []}
    },
    "relationships": {
        "r1": {"id": "r1", "type": "Composition", "source": {"element": "2"}, "target": {"element": "3"}},
        "r2": {"id": "r2", "type": "Composition", "source": {"element": "4"}, "target": {"element": "3"}},
        "r3": {"id": "r3", "type": "Aggregation", "source": {"element": "1"}, "target": {"element": "5"}}
    }
}
"""
