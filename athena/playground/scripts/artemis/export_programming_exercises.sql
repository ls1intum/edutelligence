-- Drop temporary tables if they exist
DROP TEMPORARY TABLE IF EXISTS temp_course_programming_exercises;
DROP TEMPORARY TABLE IF EXISTS temp_exam_programming_exercises;
DROP TEMPORARY TABLE IF EXISTS relevant_programming_exercises;
DROP TEMPORARY TABLE IF EXISTS latest_rated_programming_results;
DROP TEMPORARY TABLE IF EXISTS latest_rated_programming_submissions;

-- Create temporary table for relevant course programming exercises
CREATE TEMPORARY TABLE temp_course_programming_exercises AS
SELECT
  DISTINCT e.id,
  c.id AS course_id,
  0 as is_exam_exercise -- Course exercises
FROM
  exercise e
  JOIN course c ON e.course_id = c.id
WHERE
  e.discriminator = 'P'
  AND c.test_course = 0
  AND e.included_in_overall_score <> 'NOT_INCLUDED'
  AND e.course_id is not NULL
  AND c.id <> 12; -- old Software Engineering Essentials course

-- Create temporary table for relevant exam programming exercises
CREATE TEMPORARY TABLE temp_exam_programming_exercises AS
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

-- Combine temp tables to form relevant_programming_exercises
CREATE TEMPORARY TABLE relevant_programming_exercises AS
SELECT * FROM temp_course_programming_exercises
UNION
SELECT * FROM temp_exam_programming_exercises;

-- Create temporary table for latest rated programming results
CREATE TEMPORARY TABLE latest_rated_programming_results as
select r.* 
from result r
join (
	select 
		r1.participation_id,
		r1.submission_id,
		MAX(r1.completion_date) as latest_completion_date
	from relevant_programming_exercises pe
	join participation p on p.exercise_id = pe.id 
	join result r1 on r1.participation_id = p.id
	where r1.rated = 1
	group by r1.participation_id, r1.submission_id
) r1 on r1.participation_id = r.participation_id and r1.submission_id = r.submission_id and r1.latest_completion_date = r.completion_date;

-- Create temporary table for latest rated programming submissions
CREATE TEMPORARY TABLE latest_rated_programming_submissions as
select s.*
from submission s 
join (
	select 
	    s1.participation_id,
	    MAX(s1.submission_date) as latest_submission
	from relevant_programming_exercises pe
	join participation p on p.exercise_id = pe.id 
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
        p.id,
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
                'file_path',
                COALESCE(SUBSTRING_INDEX(SUBSTRING_INDEX(f.reference, 'file:', -1), '_line:', 1), NULL),
                'line_start',
                IF( -- If line number is not NULL, add 1 to it (because line numbers start at 1 in the IDE)
                  f.reference IS NOT NULL, 
                  COALESCE(CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(f.reference, '_line:', -1), 'file:', -1) AS UNSIGNED), NULL) + 1,
                  NULL
                ),
                'line_end',
                NULL,
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
            and f.`type` <> 3 -- Ignore feedback of type AUTOMATIC (unit tests, SCA, Submission Policy - for now until we have a Athena indicator!)
        )
      )
    )
  ) AS exercise_data
from
  relevant_programming_exercises pe
  join exercise e on pe.id = e.id
  join course c on pe.course_id = c.id
  join participation p on p.exercise_id = pe.id
  join latest_rated_programming_submissions s on s.participation_id = p.id
  join latest_rated_programming_results r on r.submission_id = s.id
WHERE
  e.id IN :exercise_ids
GROUP BY
  pe.id,
  pe.course_id;