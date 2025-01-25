"""
The data structure will be as follows:
credits: {submission_id: {approach: [credits]}, { submission_id: {approach: [credits]} ...}
grading_instructions_used: {submission_id: {approach: [grading_instruction_id]}}    
Tutor has the reserved "Tutor" key in the approach field.
"""
def pre_processing(data):
    tutor_feedback = data["data"]["tutor_feedbacks"]
    exercise = data["data"]["exercise"]
    results = data["data"]["results"]

    exercise_id,grading_criteria,max_points = process_exercise(exercise)
    credits_per_submission,grading_instructions_used,submission_ids,experiment_id = process_results(results)
    credits_per_submission,grading_instructions_used = process_tutor_feedback(credits_per_submission,grading_instructions_used,submission_ids,tutor_feedback)
    return credits_per_submission,grading_instructions_used,exercise_id,grading_criteria,max_points,experiment_id
def process_exercise(exercise):
    exercise_id = exercise["id"]
    grading_criteria = exercise["grading_criteria"]
    max_points = exercise["max_points"]    
    return exercise_id,grading_criteria,max_points

def process_results(results):
    submission_ids = []
    credits_per_submission = {}
    grading_instructions_used = {} 
    for aggregated_results in results:
        for key,result in aggregated_results.items():
            approach = result["name"]
            all_suggestions = result["submissionsWithFeedbackSuggestions"]
            experiment_id = result["experimentId"]
            for submission_id, suggestions in all_suggestions.items():
                submission_ids.append(submission_id)
                feedbackSuggestions = suggestions["suggestions"]
                if submission_id not in credits_per_submission:
                    credits_per_submission[submission_id] = {}
                if submission_id not in grading_instructions_used:
                    grading_instructions_used[submission_id] = {}
                for suggestion in feedbackSuggestions: 
                    if(approach) not in credits_per_submission[submission_id]:
                        credits_per_submission[submission_id][approach] = []
                    if(approach) not in grading_instructions_used[submission_id]:
                        grading_instructions_used[submission_id][approach] = []
                    credits_per_submission[submission_id][approach].append(suggestion["credits"])
                    grading_instructions_used[submission_id][approach].append(suggestion["structured_grading_instruction_id"])
                    
    return credits_per_submission,grading_instructions_used,set(submission_ids),experiment_id
def process_tutor_feedback(credits_per_submission,grading_instructions_used,submission_ids,tutor_feedbacks):
    for tutor_feedback in tutor_feedbacks:
        if "Tutor" not in credits_per_submission[str(tutor_feedback["submission_id"])]:
            credits_per_submission[str(tutor_feedback["submission_id"])]["Tutor"] = []
        credits_per_submission[str(tutor_feedback["submission_id"])]["Tutor"].append(tutor_feedback["credits"])
        
        if "Tutor" not in grading_instructions_used[str(tutor_feedback["submission_id"])]:
            grading_instructions_used[str(tutor_feedback["submission_id"])]["Tutor"] = []
        if("structured_grading_instruction_id" in tutor_feedback):
            grading_instructions_used[str(tutor_feedback["submission_id"])]["Tutor"].append(tutor_feedback["structured_grading_instruction_id"])
    return credits_per_submission,grading_instructions_used