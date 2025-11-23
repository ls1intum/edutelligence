-- Drop temporary tables if they exist
DROP TEMPORARY TABLE IF EXISTS temp_course_exercises;
DROP TEMPORARY TABLE IF EXISTS temp_exam_exercises;
DROP TEMPORARY TABLE IF EXISTS relevant_modeling_exercises;
DROP TEMPORARY TABLE IF EXISTS latest_rated_modeling_results;
DROP TEMPORARY TABLE IF EXISTS latest_rated_modeling_submissions;

-- Create temporary table for relevant course modeling exercises
CREATE TEMPORARY TABLE temp_course_exercises AS
SELECT
  DISTINCT e.id,
  c.id AS course_id,
  0 AS is_exam_exercise
FROM
  exercise e
  JOIN course c ON e.course_id = c.id
WHERE
  e.discriminator = 'M'
  AND c.test_course = 0
  AND c.id <> 39 -- tutorial course
  AND e.included_in_overall_score <> 'NOT_INCLUDED'
  AND e.course_id IS NOT NULL;

-- Create temporary table for relevant exam modeling exercises
CREATE TEMPORARY TABLE temp_exam_exercises AS
SELECT
  DISTINCT e.id,
  c.id AS course_id,
  1 AS is_exam_exercise
FROM
  course c,
  exam ex,
  exercise_group eg,
  exercise e
WHERE
  e.discriminator = 'M'
  AND c.test_course = 0
  AND c.id <> 39 -- tutorial course
  AND e.included_in_overall_score <> 'NOT_INCLUDED'
  AND e.course_id IS NULL
  AND ex.course_id = c.id
  AND ex.test_exam = 0
  AND eg.exam_id = ex.id
  AND e.exercise_group_id = eg.id;

-- Combine to relevant_modeling_exercises
CREATE TEMPORARY TABLE relevant_modeling_exercises AS
SELECT * FROM temp_course_exercises
UNION
SELECT * FROM temp_exam_exercises;

-- Latest rated modeling results
CREATE TEMPORARY TABLE latest_rated_modeling_results AS
SELECT r.*
FROM result r
JOIN (
  SELECT
    r1.participation_id,
    r1.submission_id,
    MAX(r1.completion_date) AS latest_completion_date
  FROM relevant_modeling_exercises me
  JOIN participation p ON p.exercise_id = me.id
  JOIN result r1 ON r1.participation_id = p.id
  JOIN submission s ON r1.submission_id = s.id
  WHERE r1.rated = 1 AND s.submitted = 1 AND s.model IS NOT NULL AND TRIM(s.model) <> ''
  GROUP BY r1.participation_id, r1.submission_id
) r1 ON r1.participation_id = r.participation_id
     AND r1.submission_id = r.submission_id
     AND r1.latest_completion_date = r.completion_date;

-- Latest rated modeling submissions
CREATE TEMPORARY TABLE latest_rated_modeling_submissions AS
SELECT s.*
FROM submission s
JOIN (
  SELECT
    s1.participation_id,
    MAX(s1.submission_date) AS latest_submission
  FROM relevant_modeling_exercises me
  JOIN participation p ON p.exercise_id = me.id
  JOIN latest_rated_modeling_results r ON r.participation_id = p.id
  JOIN submission s1 ON r.submission_id = s1.id
  WHERE s1.submitted = 1 AND r.rated = 1 AND s1.model IS NOT NULL AND TRIM(s1.model) <> ''
  GROUP BY s1.participation_id
) s1 ON s1.participation_id = s.participation_id AND s1.latest_submission = s.submission_date;

-- Increase group_concat limit
SET SESSION group_concat_max_len = 1000000;

-- Final modeling exercise export
SELECT
  JSON_OBJECT(
    'id', e.id,
    'course_id', me.course_id,
    'title', CONCAT(e.title, IFNULL(CONCAT(' (', c.semester, ')'), '')),
    'type', 'modeling',
    'diagram_type', e.diagram_type,
    'grading_instructions', e.grading_instructions,
    'grading_criteria',
    (
      SELECT JSON_ARRAYAGG(
        JSON_OBJECT(
          'id', gc.id,
          'title', gc.title,
          'structured_grading_instructions',
          (
            SELECT JSON_ARRAYAGG(
              JSON_OBJECT(
                'id', gi.id,
                'credits', gi.credits,
                'feedback', gi.feedback,
                'grading_scale', gi.grading_scale,
                'usage_count', gi.usage_count,
                'instruction_description', gi.instruction_description
              )
            )
            FROM grading_instruction gi
            WHERE gi.grading_criterion_id = gc.id
          )
        )
      )
      FROM grading_criterion gc
      WHERE gc.exercise_id = e.id
    ),
    'problem_statement', e.problem_statement,
    'example_solution', e.example_solution_model,
    'max_points', e.max_points,
    'bonus_points', e.bonus_points,
    'meta', JSON_OBJECT(),
    'submissions', JSON_ARRAYAGG(
      JSON_OBJECT(
        'id', p.id,
        'model', s.model,
        'score', r.score,
        'student_id', p.student_id,
        'meta', JSON_OBJECT(),
        'feedbacks', (
          SELECT JSON_ARRAYAGG(
            JSON_OBJECT(
              'id', f.id,
              'description', CASE
                WHEN f.detail_text <> '' AND gi.feedback <> '' THEN CONCAT(gi.feedback, '\n\n', f.detail_text)
                WHEN gi.feedback <> '' THEN gi.feedback
                ELSE COALESCE(f.detail_text, '')
              END,
              'title', CASE
                WHEN f.text <> '' AND gc.title <> '' THEN CONCAT(f.text, '\n', gc.title)
                WHEN f.text <> '' THEN f.text
                ELSE COALESCE(gc.title, '')
              END,
              'structured_grading_instruction_id', f.grading_instruction_id,
              'credits', f.credits,
              'type', f.type,
              'reference', f.reference,
              'meta', JSON_OBJECT()
            )
          )
          FROM feedback f
          LEFT JOIN grading_instruction gi ON f.grading_instruction_id = gi.id
          LEFT JOIN grading_criterion gc ON gi.grading_criterion_id = gc.id
          WHERE f.result_id = r.id
        )
      )
    )
  ) AS exercise_data
FROM relevant_modeling_exercises me
JOIN exercise e ON me.id = e.id
JOIN course c ON me.course_id = c.id
JOIN participation p ON p.exercise_id = me.id
JOIN latest_rated_modeling_submissions s ON s.participation_id = p.id
JOIN latest_rated_modeling_results r ON r.submission_id = s.id
WHERE e.id IN :exercise_ids
  AND s.model IS NOT NULL
GROUP BY me.id, me.course_id;
