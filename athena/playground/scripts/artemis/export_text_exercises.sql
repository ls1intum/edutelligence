-- Drop temp_course_exercises if it exists
DROP TEMPORARY TABLE IF EXISTS temp_course_exercises;

-- Drop temp_exam_exercises if it exists
DROP TEMPORARY TABLE IF EXISTS temp_exam_exercises;

-- Drop relevant_text_exercises if it exists
DROP TEMPORARY TABLE IF EXISTS relevant_text_exercises;

-- Create temporary table for relevant course exercises
CREATE TEMPORARY TABLE temp_course_exercises AS
SELECT
  DISTINCT e.id,
  c.id AS course_id,
  0 as is_exam_exercise
FROM
  exercise e
  JOIN course c ON e.course_id = c.id
WHERE
  e.discriminator = 'T'
  AND c.test_course = 0
  AND e.included_in_overall_score <> 'NOT_INCLUDED'
  AND e.course_id is not NULL;

-- Create temporary table for relevant exam exercises
CREATE TEMPORARY TABLE temp_exam_exercises AS
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

-- Combine temp tables to form relevant_text_exercises
CREATE TEMPORARY TABLE relevant_text_exercises AS
SELECT * FROM temp_course_exercises
UNION
SELECT * FROM temp_exam_exercises;

-- Make sure we don't run into the group_concat_max_len limit
SET SESSION group_concat_max_len = 1000000;

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
        p.id,
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
                CASE 
                   WHEN f.detail_text <> '' AND gi.feedback <> '' THEN CONCAT(gi.feedback, '\n\n', f.detail_text)
                   WHEN gi.feedback <> '' THEN gi.feedback
                   ELSE COALESCE(f.detail_text, '')
                END,
                'title',
                CASE 
                  WHEN f.text <> '' AND gc.title <> '' THEN CONCAT(f.text, '\n', gc.title)
                  WHEN f.text <> '' THEN f.text
                  ELSE COALESCE(gc.title, '')
                END,
                'index_start',
                tb.start_index,
                'index_end',
                tb.end_index,
                'credits',
                f.credits,
                'type',
                f.`type`,
                'meta',
                JSON_OBJECT(
                  'grading_instruction_id',
                  f.grading_instruction_id
                )
              )
            )
          from
            feedback f
            left join text_block tb on tb.feedback_id = f.id
            left join grading_instruction gi on f.grading_instruction_id = gi.id
            left join grading_criterion gc on gi.grading_criterion_id  = gc.id
          where
            f.result_id = r.id
        )
      )
    )
  ) AS exercise_data
from
  relevant_text_exercises te
  join exercise e on te.id = e.id
  join course c on te.course_id = c.id
  join participation p on p.exercise_id = te.id
  join result r on r.participation_id = p.id
  join submission s on r.submission_id = s.id
WHERE
  e.id IN :exercise_ids
  and s.`text` is not null
  and s.submitted = 1
  and r.rated = 1
GROUP BY
  te.id,
  te.course_id;