import json
def run_evaluation(results):
    return """ <html> 
<head>
<title>Module Text LLM</title>
</head>
<body>
<h1>Module Text LLM</h1>
<p>Module Text LLM is running.</p>
</body>
</html>
"""
def pre_processing(data):
    print(data)
    # for key in data["data"]:
    #     print (key)
    # tutor_feedback = data["data"]["tutor_feedbacks"]
    # exercise = data["data"]["exercise"]
    # results = data["data"]["results"]
    # process_exercise(exercise)
    # return None,None

def process_exercise(exercise):
    # Missing feedback data from tutor. 
    exercise_id = exercise["id"]
    grading_criteria = exercise["grading_criteria"]
    max_points = exercise["max_points"]
    problem_statement = exercise["problem_statement"]
    
    print(exercise)
    pass

def process_results(results):
    print(results)
    pass
# def extract_credits(results):
    
#     source = get_model_name(filename, directory_approaches)
#                 models.append(source)

#                 suggestions = data.get("submissionsWithFeedbackSuggestions", {})
#                 for submission_id, details in suggestions.items():
                    
#                     if int(submission_id) not in results:
#                         results[int(submission_id)] = {}
#                     if source not in results[int(submission_id)]:
#                     # for suggestion in details.get("suggestions", []):
#                         results[int(submission_id)][source] = details.get("suggestions", {})
#                         # {'feedbacks': []}
                    
#                     # Add filename metadata to each suggestion
#                     # for suggestion in details.get("suggestions", []):
#                     #     suggestion["source"] = os.path.splitext(filename)[0]
#                     #     results[submission_id]['feedbacks'].append(suggestion)
#     return results,models     
    # return json.dumps(data)
