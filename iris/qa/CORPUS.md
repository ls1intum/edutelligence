# Iris benchmark corpus

This is the human-readable inventory of the 50 maintained benchmark situations.
Every row has a different request and evaluation target. Situations may share a
course environment or repository when they exercise different product behavior,
but the former low/moderate/high rewrites of the same request have been removed.

This experimental version keeps the total fixed at 50 and replaces near-ceiling
situations with difficult cases that require ambiguity handling, multi-step
evidence use, or deliberate tool selection. The preserved v1 corpus remains
available on `iris/quality-assurance-simple-v1-checkpoint`.

| ID                                    | Use case           | Mode                        | Support    | Difficulty   | Situation                                            |
| ------------------------------------- | ------------------ | --------------------------- | ---------- | ------------ | ---------------------------------------------------- |
| `autonomous-logistics-optout`         | `autonomous_tutor` | `—`                         | `high`     | `foundation` | Autonomous logistics discussion with hidden content  |
| `autonomous-social-no-response`       | `autonomous_tutor` | `—`                         | `low`      | `foundation` | Social post needs no autonomous response             |
| `autonomous-extension-dispute`        | `autonomous_tutor` | `—`                         | `moderate` | `advanced`   | Disputed extension policy and approval scope         |
| `course-prerequisite-chain-high`      | `chat`             | `COURSE_CHAT`               | `high`     | `advanced`   | Multi-stage prerequisite recovery plan               |
| `course-three-mcqs-german-high`       | `chat`             | `COURSE_CHAT`               | `high`     | `foundation` | Three German course MCQs                             |
| `course-exercise-priorities-high`     | `chat`             | `COURSE_CHAT`               | `high`     | `foundation` | Exercise-history priority analysis                   |
| `course-exercise-history-low`         | `chat`             | `COURSE_CHAT`               | `low`      | `foundation` | Exercise-history interpretation with low support     |
| `course-exam-accommodation-low`       | `chat`             | `COURSE_CHAT`               | `low`      | `advanced`   | Conflicting exam accommodation evidence              |
| `course-memory-low`                   | `chat`             | `COURSE_CHAT`               | `low`      | `foundation` | Personalized explanation using learner memory        |
| `course-team-milestone-low`           | `chat`             | `COURSE_CHAT`               | `low`      | `advanced`   | Team milestone ownership conflict                    |
| `course-deadline-conflict-moderate`   | `chat`             | `COURSE_CHAT`               | `moderate` | `advanced`   | Deadline conflict and prerequisite planning          |
| `course-one-mcq-moderate`             | `chat`             | `COURSE_CHAT`               | `moderate` | `foundation` | One course MCQ for practice                          |
| `course-upcoming-deadline-moderate`   | `chat`             | `COURSE_CHAT`               | `moderate` | `foundation` | Upcoming unfinished exercise deadline                |
| `lecture-calibration-high`            | `chat`             | `LECTURE_CHAT`              | `high`     | `advanced`   | Accuracy and calibration source conflict             |
| `lecture-retrieval-high`              | `chat`             | `LECTURE_CHAT`              | `high`     | `foundation` | Retrieval across lecture sections                    |
| `lecture-three-mcqs-high`             | `chat`             | `LECTURE_CHAT`              | `high`     | `foundation` | Three grounded lecture MCQs                          |
| `lecture-german-missing-low`          | `chat`             | `LECTURE_CHAT`              | `low`      | `foundation` | German question with insufficient material           |
| `lecture-linearizability-low`         | `chat`             | `LECTURE_CHAT`              | `low`      | `advanced`   | Linearizability history reconstruction               |
| `lecture-slide-low`                   | `chat`             | `LECTURE_CHAT`              | `low`      | `foundation` | Current-slide concept question with low support      |
| `lecture-dijkstra-erratum-moderate`   | `chat`             | `LECTURE_CHAT`              | `moderate` | `advanced`   | Dijkstra wording conflict and counterexample         |
| `lecture-isolation-anomaly-moderate`  | `chat`             | `LECTURE_CHAT`              | `moderate` | `advanced`   | Isolation-level anomaly trace                        |
| `lecture-slide-injection-moderate`    | `chat`             | `LECTURE_CHAT`              | `moderate` | `foundation` | Prompt injection embedded in lecture material        |
| `lecture-video-moderate`              | `chat`             | `LECTURE_CHAT`              | `moderate` | `foundation` | Current video timestamp question                     |
| `prog-hm-inference-high`              | `chat`             | `PROGRAMMING_EXERCISE_CHAT` | `high`     | `advanced`   | Higher-order type-inference investigation            |
| `prog-incremental-workbook-high`      | `chat`             | `PROGRAMMING_EXERCISE_CHAT` | `high`     | `advanced`   | Incremental workbook state investigation             |
| `prog-off-by-one-high`                | `chat`             | `PROGRAMMING_EXERCISE_CHAT` | `high`     | `foundation` | High-support off-by-one debugging                    |
| `prog-secret-log-high`                | `chat`             | `PROGRAMMING_EXERCISE_CHAT` | `high`     | `foundation` | Secret-bearing build log and repository injection    |
| `prog-compile-low`                    | `chat`             | `PROGRAMMING_EXERCISE_CHAT` | `low`      | `foundation` | Compile failure diagnosis with low support           |
| `prog-concept-low`                    | `chat`             | `PROGRAMMING_EXERCISE_CHAT` | `low`      | `foundation` | General Python queue concept without tools           |
| `prog-german-build-low`               | `chat`             | `PROGRAMMING_EXERCISE_CHAT` | `low`      | `foundation` | German compiler diagnosis with low support           |
| `prog-solution-injection-low`         | `chat`             | `PROGRAMMING_EXERCISE_CHAT` | `low`      | `foundation` | Direct solution request with prompt injection        |
| `prog-build-event-moderate`           | `chat`             | `PROGRAMMING_EXERCISE_CHAT` | `moderate` | `foundation` | Proactive build failure intervention                 |
| `prog-custom-conflict-moderate`       | `chat`             | `PROGRAMMING_EXERCISE_CHAT` | `moderate` | `foundation` | Conflicting custom instructions and solution request |
| `prog-failed-test-moderate`           | `chat`             | `PROGRAMMING_EXERCISE_CHAT` | `moderate` | `foundation` | Failed hidden test with prior debugging history      |
| `prog-latest-submission-moderate`     | `chat`             | `PROGRAMMING_EXERCISE_CHAT` | `moderate` | `foundation` | Latest submission visibility boundary                |
| `text-astar-proof-high`               | `chat`             | `TEXT_EXERCISE_CHAT`        | `high`     | `advanced`   | Interacting A-star proof errors                      |
| `text-example-confidential-high`      | `chat`             | `TEXT_EXERCISE_CHAT`        | `high`     | `foundation` | Confidential example solution with high scaffolding  |
| `text-experiment-report-high`         | `chat`             | `TEXT_EXERCISE_CHAT`        | `high`     | `advanced`   | Leakage and uncertainty in an experiment report      |
| `text-literature-synthesis-high`      | `chat`             | `TEXT_EXERCISE_CHAT`        | `high`     | `advanced`   | Contradictory literature synthesis review            |
| `text-causal-claim-low`               | `chat`             | `TEXT_EXERCISE_CHAT`        | `low`      | `advanced`   | Correlation and causal-claim diagnosis               |
| `text-ablation-ambiguity-low`         | `chat`             | `TEXT_EXERCISE_CHAT`        | `low`      | `advanced`   | Ambiguous adaptive-hints evaluation critique         |
| `text-write-injection-low`            | `chat`             | `TEXT_EXERCISE_CHAT`        | `low`      | `foundation` | Replacement-answer request with prompt injection     |
| `text-amortized-proof-moderate`       | `chat`             | `TEXT_EXERCISE_CHAT`        | `moderate` | `advanced`   | Amortized-analysis proof repair                      |
| `text-outline-moderate`               | `chat`             | `TEXT_EXERCISE_CHAT`        | `moderate` | `foundation` | Argument outline and structure guidance              |
| `text-privacy-argument-moderate`      | `chat`             | `TEXT_EXERCISE_CHAT`        | `moderate` | `advanced`   | Privacy trade-off argument review                    |
| `global-retake-window`                | `global_search`    | `—`                         | `—`        | `advanced`   | Retake eligibility across interacting time rules     |
| `global-navigation-no-answer`         | `global_search`    | `—`                         | `—`        | `foundation` | No-hit navigation skips answer generation            |
| `tutor-stream-recovery-investigation` | `tutor_suggestion` | `PROGRAMMING_EXERCISE_CHAT` | `high`     | `advanced`   | Distributed stream recovery investigation            |
| `tutor-hm-regeneration`               | `tutor_suggestion` | `PROGRAMMING_EXERCISE_CHAT` | `high`     | `advanced`   | Regeneration across type-inference failures          |
| `tutor-workbook-investigation`        | `tutor_suggestion` | `PROGRAMMING_EXERCISE_CHAT` | `high`     | `advanced`   | Tutor guidance for stateful workbook failures        |
