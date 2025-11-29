---
title: Structure of a Module
---

An Athena Module must provide functionality by using the provided Python
decorators from the `athena` package. A module essentially just provides
a set of functions that are called by the Athena framework. Any
decorated function accessible through the `__main__.py` entry point of
the module will be called by the framework. You can however only have
exactly one function per decorator.

# Typical File Structure

You can see a typical module file structure in the provided
`module_example` in this repository.

``` text
module_example
├── module_example
│   └── __main__.py
├── .env
├── docker-compose.yml
├── pyproject.toml
├── poetry.lock
└── README.md
```

Explanation of the files:

- `module_example`: Your Python package. It is necessary that the name
  is the same as the name of the directory, because this is the only way
  that the resulting Python package can be imported with the proper
  name.
- `module_example/__main__.py`: The entry point of your module. This is
  the file that will be executed by the Athena framework. It must
  contain or import the decorated functions that you want to use.
- `.env`: The environment file for the module. It contains the
  environment variables that are passed to the module. See the section
  on environment variables for more information.
- `docker-compose.yml`: The docker-compose file for the module. It
  contains the configuration for the docker container that will be used
  to run the module. You can add additional services here, which will be
  available to the module. The required minimum is a `main` service that
  runs the module.
- `pyproject.toml`: The poetry configuration file for the module. It
  contains the dependencies of the module. You can add additional
  dependencies here by using the `poetry add` command.
- `poetry.lock`: The poetry lock file for the module. It contains the
  exact versions of the dependencies of the module. You should not edit
  this file manually. You should however commit it to your repository.
- `README.md`: The readme file for the module with additional
  information about the module.

# Available Decorators

The following decorators are available. Typically, the respective
functions are called in the order as they are listed here.

## Consume Submissions

Get submissions for an exercise. This function is usually called when
the exercise deadline is reached in the LMS. The module for the exercise
will receive the submissions at the function annotated with
`@submission_consumer`.

Example:  
``` python
from athena import *

@submissions_consumer
def receive_submissions(exercise: Exercise, submissions: List[Submission]):
    ...
```

## Select Submission

Select the submission to grade next out out of many submissions. The LMS
would usually call this right before a tutor can start grading a
submission. You should get a list of all submissions that are not graded
yet. The module will receive the request at the function annotated with
`@submission_selector`.

Example:  
``` python
from athena import *

@submission_selector
def select_submission(exercise: Exercise, submissions: List[Submission]) -> Submission:
    ...
    # Do something with the submissions and return the one that should be assessed next
    # This example always chooses the first submission
    return submissions[0]
```

## Consume Feedback

Get a list of given feedback. This usually happens when someone gives
feedback on the submission in the LMS. The module will receive the
feedback at the function annotated with `@feedback_consumer`.

Example:  
``` python
from athena import *

@feedback_consumer
def process_incoming_feedback(exercise: Exercise, submission: Submission, feedbacks: List[Feedback]):
    ...
```

## Provide Feedback Suggestions

Get a list of feedback suggestions for a submission. Then provide a list
of suggestions for feedback. The LMS would usually call this when a
tutor starts grading a submission. The module will receive the request
at the function annotated with `@feedback_provider`.

Example:  
``` python
from athena import *

@feedback_provider
def suggest_feedback(exercise: Exercise, submission: Submission) -> List[Feedback]:
    # Do something with the submission and return a list of feedback suggestions
    ...
    return [
        Feedback(
            ...
        )
    ]
```

Provide Config Schema (Optional)
\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~~ Get a schema for config
options of the module as json schema. The config complying to the schema
can then be provided in the header of a request
<span class="title-ref">X-Module-Config</span> to override the default
values. The module can decorate one pydantic model with
`@config_schema_provider` to provide the schema and should have default
values set for all fields as default configuration. The configuration
class can be appended to the function signature of all other decorators
to provide the configuration to the function.

Example:  
``` python
from athena import *

@config_schema_provider
class Configuration(BaseModel):
    debug: bool = Field(False, description="Whether the module is in debug mode.")
    ...
```

Provide Evaluation (Optional) \~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~~ Get an
arbitrary evaluation for a submission with historical `true_feedback`
and feedback suggestions `predicted_feedback`. The Playground would
usually call this when conducting an evaluation during an experiment.
The module will receive the request at the function annotated with
`@evaluation_provider`.

If you want to have the `/evaluation` endpoint available during the
Playground evaluation mode, you need to set `supports_evaluation = true`
in the `modules.ini` and `modules.docker.ini` files.

Example:  
``` python
from athena import *

@evaluation_provider
def evaluate_feedback(exercise: Exercise, submission: Submission, true_feedbacks: List[Feedback], predicted_feedbacks: List[Feedback]) -> Any:
    # Do something with the true and predicted feedback and return the evaluation result
    ...
    # Example: Generate some example evaluation result
    evaluation_results = []
    true_feedback_embeddings = [random.random() for _ in true_feedbacks] 
    predicted_feedback_embeddings = [random.random() for _ in predicted_feedbacks]
    for feedback, embedding in zip(predicted_feedbacks, predicted_feedback_embeddings):
        feedback_evaluation = {
            "feedback_id": feedback.id,
            "embedding": embedding,
            "has_match": len([t for t in true_feedback_embeddings if abs(t - embedding) < 0.1]) > 0,
            "correctness": random.random()
        }
        evaluation_results.append(feedback_evaluation)
    ...
    # Return arbitrary evaluation results
    return evaluation_results
```

# Environment Variables

You should provide at least the following environment variables for your
module to work properly:

- `MODULE_NAME`: The name of the module. This is used to identify the
  module in the LMS. It has to exactly match the name of the module
  directory.
- `MODULE_TYPE`: The type of exercises that the module supports, e.g.
  `text` or `programming`.
- `PORT`: A unique port for the module to run on. This is used to
  prevent conflicts when running multiple modules on the same machine.
  We suggest counting up from `5001` (which is the example module).
- `PRODUCTION`: 0 or 1, depending on whether the module is running in
  production mode or not. If the value is 0, the module will auto-reload
  on changes.
- `COMPOSE_PROJECT_NAME=athena_${MODULE_NAME}`: Keep this as-is. Is it
  used to scope the docker service names.
