import dotenv

dotenv.load_dotenv(override=True)

# Approach Discovery
# By importing these modules, we trigger the @register_approach decorators
# within them, populating our central registry.
print("Registering text assessment approaches...")
from .basic_approach import generate_suggestions
from .chain_of_thought_approach import generate_suggestions
from .cot_learner_profile import generate_suggestions
from .divide_and_conquer import generate_suggestions
from .self_consistency import generate_suggestions
print("Registration complete.")