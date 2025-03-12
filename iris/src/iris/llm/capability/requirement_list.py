class RequirementList:
    """A class to represent the requirements you want to match against"""

    # Maximum cost in $ per 1k input tokens
    input_cost: float | None
    # Maximum cost in $ per 1k output tokens
    output_cost: float | None
    # The minimum GPT version that the model should be roughly equivalent to
    gpt_version_equivalent: float | None
    # The minimum speed of the model in tokens per second
    speed: float | None
    # The minimum context length of the model in tokens
    context_length: int | None
    # The vendor of the model e.g. "OpenAI" or "Anthropic"
    vendor: str | None
    # Whether the model should be privacy compliant to be used for sensitive data
    privacy_compliance: bool | None
    # Whether the model should be self-hosted
    self_hosted: bool | None
    # Whether the model should support image recognition
    image_recognition: bool | None
    # Whether the model should support a JSON mode
    json_mode: bool | None

    def __init__(
        self,
        input_cost: float | None = None,
        output_cost: float | None = None,
        gpt_version_equivalent: float | None = None,
        speed: float | None = None,
        context_length: int | None = None,
        vendor: str | None = None,
        privacy_compliance: bool | None = None,
        self_hosted: bool | None = None,
        image_recognition: bool | None = None,
        json_mode: bool | None = None,
    ) -> None:
        self.input_cost = input_cost
        self.output_cost = output_cost
        self.gpt_version_equivalent = gpt_version_equivalent
        self.speed = speed
        self.context_length = context_length
        self.vendor = vendor
        self.privacy_compliance = privacy_compliance
        self.self_hosted = self_hosted
        self.image_recognition = image_recognition
        self.json_mode = json_mode
