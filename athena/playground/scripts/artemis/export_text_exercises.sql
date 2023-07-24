DROP VIEW IF EXISTS relevant_text_exercises;

/*
 * All relevant text exercises
 * 
 * Relevant ones are:
 *  - Text exercises
 * 	- Not part of a test course
 *  - Influencing the grade
 *  - OR is an exam exercise of a non-test exam
 */
CREATE VIEW relevant_text_exercises AS -- Select course exercises
SELECT
  DISTINCT e.id,
  c.id AS course_id,
  0 as is_exam_exercise
FROM
  exercise e
  JOIN course c ON e.course_id = c.id
  JOIN participation p ON p.exercise_id = e.id
  JOIN result r ON r.participation_id = p.id
WHERE
  e.discriminator = 'T'
  AND c.test_course = 0
  AND e.included_in_overall_score <> 'NOT_INCLUDED'
  AND e.course_id is not NULL
UNION
-- Select exam exercises
SELECT
  DISTINCT e.id,
  c.id AS course_id,
  1 as is_exam_exercise
FROM
  course c,
  exam ex,
  exercise_group eg,
  exercise e
WHERE
  e.discriminator = 'T'
  AND c.test_course = 0
  AND e.included_in_overall_score <> 'NOT_INCLUDED'
  AND e.course_id is NULL
  AND ex.course_id = c.id
  AND ex.test_exam = 0
  AND eg.exam_id = ex.id
  AND e.exercise_group_id = eg.id;

SET
  SESSION group_concat_max_len = 1000000;

-- Exercise export for playground
SELECT
  JSON_OBJECT(
    'id',
    e.id,
    'course_id',
    te.course_id,
    'title',
    CONCAT(
      e.title,
      IFNULL(CONCAT(' (', c.semester, ')'), '')
    ),
    'type',
    'text',
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
    'example_solution',
    e.example_solution,
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
        'content',
        s.`text`,
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
                'description',
                f.detail_text,
                'title',
                COALESCE(f.text, ''),
                -- Might remove fallback in the future
                'index_start',
                tb.start_index,
                'index_end',
                tb.end_index,
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
            left join text_block tb on f.reference = tb.id
          where
            r.participation_id = p.id
        )
      )
    )
  ) AS exercise_data
from
  relevant_text_exercises te
  join exercise e on te.id = e.id
  join course c on te.course_id = c.id
  join participation p on p.exercise_id = e.id
  join submission s on s.participation_id = p.id
WHERE
  e.id IN :exercise_ids
  and s.`text` is not null
  and s.submitted = 1
GROUP BY
  te.id,
  te.course_id;