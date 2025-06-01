"""Phases package for solution repository creation."""

from .phase1_planning import PlanningPhase
from .phase2_testing import TestingPhase
from .phase3_validation import ValidationPhase

__all__ = [
    "PlanningPhase",
    "TestingPhase", 
    "ValidationPhase"
] 