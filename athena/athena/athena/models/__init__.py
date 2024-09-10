"""Models are SQLAlchemy classes that represent database tables."""
# Read
# https://docs.pylonsproject.org/projects/pyramid_cookbook/en/latest/database/sqlalchemy.html#importing-all-sqlalchemy-models
# about possible issues with circular imports here.

from .db_exercise import DBExercise
from .db_submission import DBSubmission
from .db_feedback import DBFeedback
from .db_structured_grading_instruction import DBStructuredGradingInstruction
from .db_programming_exercise import DBProgrammingExercise
from .db_text_exercise import DBTextExercise
from .db_modeling_exercise import DBModelingExercise
from .db_programming_submission import DBProgrammingSubmission
from .db_text_submission import DBTextSubmission
from .db_modeling_submission import DBModelingSubmission
from .db_programming_feedback import DBProgrammingFeedback
from .db_text_feedback import DBTextFeedback
from .db_modeling_feedback import DBModelingFeedback
from .db_modeling_structured_grading_criterion import DBModelingStructuredGradingCriterion