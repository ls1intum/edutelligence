from module_text_llm.analytics.pre_processing import pre_processing
from module_text_llm.analytics.analytics import test_visualization

def compile(results):
    credits_per_submission,grading_instructions_used,exercise_id,grading_criteria,max_points = pre_processing(results)
    test_visualization(credits_per_submission) # credits_comparison.html
         
    with open("credits_comparison.html", "r", encoding="utf-8") as file:
        html_content = file.read()
    return html_content

