"""
A parser for logos model strings. Implements the grammar:

<logos-model> ::= "logos-v" <version> "__policy_" <policy-values> [ "__" <extra-params> ]

<policy-values> ::= "default=true" | "default=false" [ "__" <policy-params> ]

<policy-params> ::= <pair> { "__" <pair> }*
<pair> ::= <key> "=" <value>

<extra-params> ::= <pair> { "__" <pair> }*

<key> ::= LETTER { LETTER | DIGIT | "_" | "-" }*
<value> ::= LETTER { LETTER | DIGIT | "." | ":" | "-" }*
<version> ::= DIGIT { "." DIGIT }*
"""
from typing import Union, Dict

ALLOWED_FIELDS = {"policy"}
POLICY_FIELDS = {"accuracy", "latency", "quality", "cost", "privacy", "default"}
PRIVACY_VALUES = {"LOCAL", "CLOUD_IN_EU_BY_EU_PROVIDER", "CLOUD_IN_EU_BY_US_PROVIDER", "CLOUD_NOT_IN_EU_BY_US_PROVIDER"}


class ParserTransferDTO:
    policy: dict = dict()
    version: str
    extra: dict = dict()


def parse_model_string(model_str: str) -> ParserTransferDTO:
    """
    Parses a given logos model string.

    @raises SyntaxError: if the model string is malformed.
    @raises ValueError: if wrong attribute values are provided
    @raises AttributeError: if parameters are missing or incomplete
    """
    # Check string head
    if not model_str.startswith("logos-v"):
        raise SyntaxError("Logos model strings have to start with 'logos-v'")

    rest = model_str.replace("logos-v", "", count=1)
    params = rest.split("__")
    version = params[0]

    # Define default values
    policy: Dict[str, Union[str, bool]] = {"default": "true"}
    extra = dict()

    # Check string body
    try:
        for param in params[1:]:
            if "policy_" in param:
                vals = param.replace("policy_", "", count=1)
                # Get all "k=v"-Pairs
                for kv in vals.split("_"):
                    k, v = kv.split("=", maxsplit=1)
                    if k not in POLICY_FIELDS:
                        raise ValueError("Misplaced attribute in policy fields: %s. Allowed attributes: %s", k, POLICY_FIELDS)
                    if k == "privacy" and v not in PRIVACY_VALUES:
                        raise ValueError("Value '%s' not allowed as privacy value. Allowed types: %s", v, PRIVACY_VALUES)
                    policy[k] = v
            else:
                k, v = param.split("=", maxsplit=1)
                extra[k] = v
    except ValueError as e:
        raise SyntaxError("Invalid logos model string") from e
    if policy["default"] == "true":
        policy["default"] = True
    elif policy["default"] == "false":
        # Throw error if we don't want only default values but provided nothing else
        if len(policy) == 1:
            raise AttributeError("Non-default policy without additional attributes is not allowed. Provide at least one policy attribute to override")
        policy["default"] = False
    else:
        raise AttributeError("Missing default parameter for policy attributes")

    # Filter extra fields for allowed keys
    extra = {k: v for k, v in extra.items() if k in ALLOWED_FIELDS}

    dto = ParserTransferDTO()
    dto.policy = policy
    dto.version = version
    dto.extra = extra
    return dto
