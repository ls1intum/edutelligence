-- Drop temporary tables if they exist
DROP TEMPORARY TABLE IF EXISTS temp_course_exercises;
DROP TEMPORARY TABLE IF EXISTS temp_exam_exercises;
DROP TEMPORARY TABLE IF EXISTS relevant_text_exercises;
DROP TEMPORARY TABLE IF EXISTS latest_rated_text_results;
DROP TEMPORARY TABLE IF EXISTS latest_rated_text_submissions;

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

-- Create temporary table for latest rated text results
CREATE TEMPORARY TABLE latest_rated_text_results as
select r.* 
from result r
join (
	select 
		r1.participation_id,
		r1.submission_id,
		MAX(r1.completion_date) as latest_completion_date
	from relevant_text_exercises te
	join participation p on p.exercise_id = te.id 
	join result r1 on r1.participation_id = p.id
	where r1.rated = 1
	group by r1.participation_id, r1.submission_id
) r1 on r1.participation_id = r.participation_id and r1.submission_id = r.submission_id and r1.latest_completion_date = r.completion_date;

-- Create temporary table for latest rated text submissions
CREATE TEMPORARY TABLE latest_rated_text_submissions as
select s.*
from submission s 
join (
	select 
	    s1.participation_id,
	    MAX(s1.submission_date) as latest_submission
	from relevant_text_exercises te
	join participation p on p.exercise_id = te.id 
	join submission s1 on s1.participation_id = p.id 
	join `result` r on r.submission_id = s1.id
	where s1.submitted = 1 and r.rated = 1 and r.assessment_type <> 'AUTOMATIC'
	group by s1.participation_id
) s1 on s1.participation_id = s.participation_id and s1.latest_submission = s.submission_date;

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
  join latest_rated_text_submissions s on s.participation_id = p.id
  join latest_rated_text_results r on r.submission_id = s.id
WHERE
  e.id IN :exercise_ids
  and s.`text` is not null
GROUP BY
  te.id,
  te.course_id;