from .capability_list import (
    CapabilityList,
    always_considered_capabilities_with_default,
    capability_weights,
)
from .requirement_list import RequirementList


def capabilities_fulfill_requirements(
    capability: CapabilityList, requirements: RequirementList
) -> bool:
    """Check if the capability fulfills the requirements"""
    return all(
        getattr(capability, field).matches(getattr(requirements, field))
        for field in requirements.__dict__.keys()
        if getattr(requirements, field) is not None
    )


def calculate_capability_scores(
    capabilities: list[CapabilityList],
    requirements: RequirementList,
    invert_cost: bool = False,
) -> list[int]:
    """Calculate the scores of the capabilities against the requirements"""
    all_scores = []

    for requirement in requirements.__dict__.keys():
        requirement_value = getattr(requirements, requirement)
        if (
            requirement_value is None
            and requirement not in always_considered_capabilities_with_default
        ):
            continue

        # Calculate the scores for each capability
        scores = []
        for capability in capabilities:
            if (
                requirement_value is None
                and requirement in always_considered_capabilities_with_default
            ):
                # If the requirement is not set, use the default value if necessary
                score = getattr(capability, requirement).matches(
                    always_considered_capabilities_with_default[requirement]
                )
            else:
                score = getattr(capability, requirement).matches(requirement_value)
            # Invert the cost if required
            # The cost is a special case, as depending on how you want to use the scores
            # the cost needs to be considered differently
            if (
                requirement in ["input_cost", "output_cost"]
                and invert_cost
                and score != 0
            ):
                score = 1 / score
            scores.append(score)

        # Normalize the scores between 0 and 1 and multiply by the weight modifier
        # The normalization here is based on the position of the score in the sorted list to balance out
        # the different ranges of the capabilities
        sorted_scores = sorted(set(scores))
        weight_modifier = capability_weights[requirement]
        normalized_scores = [
            ((sorted_scores.index(score) + 1) / len(sorted_scores)) * weight_modifier
            for score in scores
        ]
        all_scores.append(normalized_scores)

    final_scores = []

    # Sum up the scores for each capability to get the final score for each list of capabilities
    for i in range(len(all_scores[0])):
        score = 0
        for j in range(len(all_scores)):
            score += all_scores[j][i]
        final_scores.append(score)

    return final_scores
