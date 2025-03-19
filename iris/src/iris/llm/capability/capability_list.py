from abc import ABCMeta

from pydantic import BaseModel, Field, model_validator


class Capability(metaclass=ABCMeta):
    """A capability to match a generic value"""

    @classmethod
    def __subclasshook__(cls, subclass) -> bool:
        return hasattr(subclass, "matches") and callable(subclass.matches)

    def matches(self, other: any) -> int:
        """Return a score for how well the capability matches the input"""
        raise NotImplementedError


class TextCapability(BaseModel):
    """A capability to match a fixed text value"""

    value: str

    def matches(self, text: str) -> int:
        return int(self.value == text)

    def __str__(self):
        return f"TextCapability({super().__str__()})"


class OrderedNumberCapability(BaseModel):
    """A capability that is better the higher the value"""

    value: int | float

    def matches(self, number: int | float) -> int | float:
        if self.value < number:
            return 0
        return self.value - number + 1

    def __str__(self):
        return f"OrderedNumberCapability({super().__str__()})"


class InverseOrderedNumberCapability(BaseModel):
    """A capability that is better the lower the value"""

    value: int | float

    def matches(self, number: int | float) -> int | float:
        if self.value > number:
            return 0
        return number - self.value + 1

    def __str__(self):
        return f"InverseOrderedNumberCapability({super().__str__()})"


class BooleanCapability(BaseModel):
    """A simple boolean capability"""

    value: bool

    def matches(self, boolean: bool) -> int:
        return int(self.value == boolean)

    def __str__(self):
        return f"BooleanCapability({str(self.value)})"


class CapabilityList(BaseModel):
    """A list of capabilities for a model"""

    # Cost in $ per 1k input tokens
    input_cost: InverseOrderedNumberCapability = Field(
        default=InverseOrderedNumberCapability(value=0)
    )
    # Output cost in $ per 1k tokens
    output_cost: InverseOrderedNumberCapability = Field(
        default=InverseOrderedNumberCapability(value=0)
    )
    # The GPT version that is roughly equivalent to the model
    gpt_version_equivalent: OrderedNumberCapability = Field(
        default=OrderedNumberCapability(value=2)
    )
    # The speed of the model in tokens per second
    speed: OrderedNumberCapability = Field(default=OrderedNumberCapability(value=0))
    # The context length of the model in tokens
    context_length: OrderedNumberCapability = Field(
        default=OrderedNumberCapability(value=0)
    )
    # The vendor of the model e.g. "OpenAI" or "Anthropic"
    vendor: TextCapability = Field(default=TextCapability(value=""))
    # Whether the model is privacy compliant and can be used for sensitive data
    privacy_compliance: BooleanCapability = Field(
        default=BooleanCapability(value=False)
    )
    # Whether the model is self-hosted
    self_hosted: BooleanCapability = Field(default=BooleanCapability(value=False))
    # Whether the model supports image recognition
    image_recognition: BooleanCapability = Field(default=BooleanCapability(value=False))
    # Whether the model supports a JSON mode
    json_mode: BooleanCapability = Field(default=BooleanCapability(value=False))

    @model_validator(mode="before")
    @classmethod
    def from_dict(cls, data: dict[str, any]):
        """Prepare the data for handling by Pydantic"""
        for key, value in data.items():
            if not isinstance(value, dict):
                data[key] = {"value": value}
        return data


# The weights for the capabilities used in the scoring
capability_weights = {
    "input_cost": 0.5,
    "output_cost": 0.5,
    "gpt_version_equivalent": 4,
    "speed": 2,
    "context_length": 0.1,
    "vendor": 1,
    "privacy_compliance": 0,
    "self_hosted": 0,
    "image_recognition": 0,
    "json_mode": 0,
}

# The default values for the capabilities that are always considered
always_considered_capabilities_with_default = {
    "input_cost": 100000000000000,
    "output_cost": 100000000000000,
}
