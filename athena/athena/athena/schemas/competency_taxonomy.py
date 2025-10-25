from enum import Enum


class CompetencyTaxonomy(Enum):
    """The taxonomy of competencies that is used to structure the competencies."""
    REMEMBER = "remember"
    UNDERSTAND = "understand"
    APPLY = "apply"
    ANALYZE = "analyze"
    EVALUATE = "evaluate"
    CREATE = "create"

    @classmethod
    def from_any_case(cls, value):
        """Convert any case to the correct enum value."""
        if isinstance(value, str):
            value_lower = value.lower()
            for member in cls:
                if member.value == value_lower:
                    return member
        raise ValueError(f"Invalid taxonomy value: {value}")
