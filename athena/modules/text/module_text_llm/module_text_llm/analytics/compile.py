from module_text_llm.analytics.pre_processing import pre_processing
from module_text_llm.analytics.analytics import create_threshold_bar_plot,percentage_within_range,test_visualization,failure_success,analyze_grading_instruction_usage, visualize_differences_histogram,normalized_absolute_difference,visualize_histogram_kde_percentages
import os
import traceback


def compile(results):
    """This function will compile the analytics for the given results
It first preprocesses the data and then calls multiple functions to generate the analytics.
All these are put together in an HTML file which is then returned as a string.
Through plotly, the figures are embedded in the HTML file and are fully interactive.
    """
    try:
        credits_per_submission,grading_instructions_used,exercise_id,grading_criteria,max_points,experiment_id,failures,submission_ids = pre_processing(results)
        directory = "module_text_llm/analytics/created_analytics"
        ensure_directory_exists(directory)
        output_file = f"{directory}/analytics_{experiment_id}.html"
        
        if file_exists(output_file):
            return get_html_content(output_file)
        
        ############################# CREDIT BASED ANALYTICS #############################
        # Define them here, must return a dict of type {"fig":fig,"html_explanation":html_explanation}
        creditPSub = test_visualization(credits_per_submission)
        histo = visualize_differences_histogram(credits_per_submission,max_points)
        kde_percent = visualize_histogram_kde_percentages(credits_per_submission,max_points)
        nmda = normalized_absolute_difference(credits_per_submission,max_points)
        fail = failure_success(credits_per_submission,failures,submission_ids)
        threshold_bar_plot = create_threshold_bar_plot(credits_per_submission,max_points)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(get_introduction())
            f.write("""
            <h2>Credits Analaytics</h2>
            <hr style="border: 3px solid black; margin: 20px 0;" />
            """)
            for i,dic in enumerate([threshold_bar_plot,fail,nmda,kde_percent,histo, creditPSub], start=1): # and use them here
                f.write(f"""
                <hr style="border: 1px solid lightgray; margin: 10px 0;" />
                <h2>Plot {i}</h2>
                """)
                f.write(dic["html_explanation"])
                f.write(dic["fig"].to_html(full_html=False, include_plotlyjs="cdn"))
            
        ############################# CREDIT BASED ANALYTICS #############################
        ####################### Grading Instruction Based Analytics #######################
            f.write("""
            <h2>Structured Grading Instruction IDs Analytics</h2>
            <hr style="border: 3px solid black; margin: 20px 0;" />
            """)
            fig,html_expl = analyze_grading_instruction_usage(grading_instructions_used)
            f.write(html_expl)
            f.write(fig.to_html(full_html=False, include_plotlyjs="cdn")) 

            f.write("</body></html>")
        ####################### Grading Instruction Based Analytics #######################

            ###### Return the analytics as an html file ########
        with open(output_file, "r", encoding="utf-8") as file:
            html_content = file.read()
    except Exception as e:
        html_content = getFallbackHtml(f"An error occurred while generating the analytics {str(e)} . Full Trace: {traceback.format_exc()}")
    return html_content

def file_exists(path) -> bool: 
    return os.path.exists(path)

def get_html_content(path):
    if file_exists(path):
        with open(path, "r", encoding="utf-8") as file:
            html_content = file.read()
        return html_content
    
    return getFallbackHtml("File was not found")
    
def getFallbackHtml(specifics: str):
    return  f"""
        <html>
  <head>
    <style>
      body {{
        font-family: Arial, sans-serif;
        background-color: #f8d7da;
        color: #721c24;
        padding: 20px;
        border: 1px solid #f5c6cb;
        border-radius: 5px;
      }}
    </style>
  </head>
  <body>
    <h2>Warning: Analytics generation failed.</h2>
    <p> Please try again. Make sure the experiment has finished! </p>
    <p> If the problem persists, please contact the administrator. </p>
    <p> Error details: {specifics} </p>
  </body>
</html>
    """
    
def get_introduction()->str:
    return """ 
<!DOCTYPE html>
<html>
<head>
    <title>Athena Analytics</title>
</head>
<body>
    <h1 style="text-align: center; font-size: 36px;">Athena Interactive Analytics of Experiment</h1>
    <p style="text-align: center; font-size: 18px; max-width: 800px; margin: 20px auto;">
        Welcome to the analytics report for the experiments. This report includes fully interactive visuals generated with Plotly. 
        You can explore the data by turning visuals on or off by clicking items in the legend. Unless otherwise specified, the analysis 
        presented here is primarily based on tutor feedback, providing insights into the underlying patterns and trends.
        
        The first section focuses on analyzing the credits awarded by each model on each submission. The second section provides a 
        analaytics on the usage of the grading instructions ids.
    </p>
"""

import os

def ensure_directory_exists(directory_path):
    if not os.path.exists(directory_path):
        os.makedirs(directory_path)
