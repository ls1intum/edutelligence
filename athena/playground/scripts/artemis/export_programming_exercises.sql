DROP VIEW IF EXISTS relevant_programming_exercises;

/*
 * All relevant programming exercises
 * 
 * Relevant ones are:
 *  - Programming exercises
 * 	- Not part of a test course
 *  - Influencing the grade
 *  - OR is an exam exercise of a non-test exam
 */
CREATE VIEW relevant_programming_exercises AS
SELECT
  DISTINCT e.id,
  c.id AS course_id,
  0 as is_exam_exercise -- Course exercises
FROM
  exercise e
  JOIN course c ON e.course_id = c.id
  JOIN participation p ON p.exercise_id = e.id
  JOIN result r ON r.participation_id = p.id
WHERE
  e.discriminator = 'P'
  AND c.test_course = 0
  AND e.included_in_overall_score <> 'NOT_INCLUDED'
  AND e.course_id is not NULL
  AND c.id <> 12 -- old Software Engineering Essentials course
UNION
SELECT
  DISTINCT e.id,
  c.id AS course_id,
  1 as is_exam_exercise -- Exam exercises
FROM
  course c,
  exam ex,
  exercise_group eg,
  exercise e
WHERE
  e.discriminator = 'P'
  AND c.test_course = 0
  AND e.included_in_overall_score <> 'NOT_INCLUDED'
  AND e.course_id is NULL
  AND ex.course_id = c.id
  AND ex.test_exam = 0
  AND eg.exam_id = ex.id
  AND e.exercise_group_id = eg.id
  AND c.id <> 12; -- old Software Engineering Essentials course

SET
  SESSION group_concat_max_len = 1000000;

-- Exercise export for playground
SELECT
  JSON_OBJECT(
    'id',
    e.id,
    'course_id',
    pe.course_id,
    'title',
    CONCAT(
      e.title,
      IFNULL(CONCAT(' (', c.semester, ')'), '')
    ),
    'type',
    'programming',
    'grading_instructions',
    CONCAT(
      e.grading_instructions,
      '\n',
      COALESCE(
        (
          SELECT
            GROUP_CONCAT(
              CONCAT(
                gc.title,
                ':\n',
                COALESCE(
                  (
                    SELECT
                      GROUP_CONCAT(
                        CONCAT(
                          '  - ',
                          gi.feedback,
                          ' (',
                          gi.credits,
                          ' credits) [',
                          gi.instruction_description,
                          ']'
                        ) SEPARATOR '\n '
                      )
                    FROM
                      grading_instruction gi
                    WHERE
                      gi.grading_criterion_id = gc.id
                  ),
                  ''
                )
              ) SEPARATOR '\n\n'
            )
          FROM
            grading_criterion gc
          WHERE
            gc.exercise_id = e.id
        ),
        ''
      )
    ),
    'problem_statement',
    e.problem_statement,
    -- repository urls will be set later by another script (after zip import)
    'solution_repository_url',
    NULL,
    'template_repository_url',
    NULL,
    'tests_repository_url',
    NULL,
    'max_points',
    e.max_points,
    'bonus_points',
    e.bonus_points,
    'meta',
    JSON_OBJECT(),
    'submissions',
    JSON_ARRAYAGG(
      JSON_OBJECT(
        'id',
        s.id,
        -- repository url will be set later by another script (after zip import)
        'repository_url',
        NULL,
        'student_id',
        p.student_id,
        'meta',
        JSON_OBJECT(),
        'feedbacks',
        (
          select
            JSON_ARRAYAGG(
              JSON_OBJECT(
                'id',
                f.id,
                'detail_text',
                f.detail_text,
                'text',
                COALESCE(f.text, ''),
                -- Might remove the f.text fallback in the future
                'reference',
                f.reference,
                'credits',
                f.credits,
                'type',
                f.`type`,
                'meta',
                JSON_OBJECT()
              )
            )
          from
            `result` r
            join feedback f on f.result_id = r.id
          where
            r.participation_id = p.id
            and f.`type` <> 3 -- Ignore feedback of type AUTOMATIC (unit tests, SCA, Submission Policy - for now until we have a Athena indicator!)
        )
      )
    )
  ) AS exercise_data
from
  relevant_programming_exercises pe
  join exercise e on pe.id = e.id
  join course c on pe.course_id = c.id
  join participation p on p.exercise_id = e.id
  join submission s on s.participation_id = p.id
WHERE
  e.id IN :exercise_ids
  and s.submitted = 1
GROUP BY
  pe.id,
  pe.course_id;