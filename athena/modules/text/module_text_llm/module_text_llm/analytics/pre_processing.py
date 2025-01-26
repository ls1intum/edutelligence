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
    credits_per_submission,grading_instructions_used,submission_ids = process_tutor_feedback(tutor_feedback)
    credits_per_submission,grading_instructions_used,submission_to_exclude,experiment_id,failures = process_results(results,credits_per_submission,grading_instructions_used,submission_ids)
    filtered_credits_per_submission = {
        key: value
        for key, value in credits_per_submission.items()
        if str(key) not in submission_to_exclude
    }
    filtered_grading_instructions_used ={
        key: value
        for key, value in grading_instructions_used.items()
        if int(key) not in submission_to_exclude
    }
    print(credits_per_submission)
    print(submission_to_exclude)
    
    print(filtered_credits_per_submission)

    # Remove submissions that did not have suggestions from all approaches, this would cause problems with analytics consistency but also failures
    
    return filtered_credits_per_submission,filtered_grading_instructions_used,exercise_id,grading_criteria,max_points,experiment_id,failures,submission_ids
def process_exercise(exercise):
    exercise_id = exercise["id"]
    
    grading_criteria = []
    if "grading_criteria" in exercise:
        grading_criteria = exercise["grading_criteria"]
        
    max_points = exercise["max_points"]    
    return exercise_id,grading_criteria,max_points

def process_results(results,credits_per_submission,grading_instructions_used,submission_ids):
    failures = {}
    submission_to_exclude = []
    for aggregated_results in results:
        for key,result in aggregated_results.items():
            approach = result["name"]
            if approach not in failures:
                failures[approach] = 0
            all_suggestions = result["submissionsWithFeedbackSuggestions"]
            experiment_id = result["experimentId"]
            for submission_id in submission_ids:
                submission_id = str(submission_id)
                print("Looking at Submission ID: ",submission_id)  
                if submission_id not in all_suggestions:
                    submission_to_exclude.append(submission_id)
                    failures[approach] += 1
                    print(f" {approach} failed to generate suggestions for submission {submission_id}")
                    continue
                else:
                    suggestions = all_suggestions[str(submission_id)]
                    feedbackSuggestions = suggestions["suggestions"]
                    for suggestion in feedbackSuggestions: 
                        if (approach) not in credits_per_submission[submission_id]:
                            credits_per_submission[submission_id][approach] = []
                        if (approach) not in grading_instructions_used[submission_id]:
                            grading_instructions_used[submission_id][approach] = []
                        credits_per_submission[submission_id][approach].append(suggestion["credits"])
                        grading_instructions_used[submission_id][approach].append(suggestion["structured_grading_instruction_id"])
                    
    return credits_per_submission,grading_instructions_used,set(submission_to_exclude),experiment_id,failures

def process_tutor_feedback(tutor_feedbacks):
    credits_per_submission = {}
    grading_instructions_used = {} 
    submission_ids = []
    for tutor_feedback in tutor_feedbacks:
        submission_ids.append(tutor_feedback["submission_id"])
        
        if str(tutor_feedback["submission_id"]) not in credits_per_submission:
            credits_per_submission[str(tutor_feedback["submission_id"])] = {}
        if "Tutor" not in credits_per_submission[str(tutor_feedback["submission_id"])]:
            credits_per_submission[str(tutor_feedback["submission_id"])]["Tutor"] = []
        credits_per_submission[str(tutor_feedback["submission_id"])]["Tutor"].append(tutor_feedback["credits"])
        # I keep the list of single credits, in case we want to compare more granularly in the future
        
        if str(tutor_feedback["submission_id"]) not in grading_instructions_used:
            grading_instructions_used[str(tutor_feedback["submission_id"])] = {}
        if "Tutor" not in grading_instructions_used[str(tutor_feedback["submission_id"])]:
            grading_instructions_used[str(tutor_feedback["submission_id"])]["Tutor"] = []
            
        if "structured_grading_instruction_id" in tutor_feedback:
            grading_instructions_used[str(tutor_feedback["submission_id"])]["Tutor"].append(tutor_feedback["structured_grading_instruction_id"])
    return credits_per_submission,grading_instructions_used,set(submission_ids)