import plotly.express as px
import plotly.graph_objects as go
import plotly.figure_factory as ff
import numpy as np
from collections import Counter

def failure_success(credits_per_submission,failures,submission_ids):
    failures_per_model = {}
    list_of_models = failures.keys()
    total_runs = len(submission_ids)
    for submission_id, approaches in credits_per_submission.items():
        for model in list_of_models:
            if model not in failures_per_model:
                failures_per_model[model] = 0
            if model not in approaches:
                failures_per_model[model] += 1
                
    successes_per_model = {model: total_runs - failures for model, failures in failures_per_model.items()}

    models = list(failures_per_model.keys())
    failures = list(failures_per_model.values())
    successes = list(successes_per_model.values())

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=models,
        y=failures,
        name='Failures',
        marker_color='red',
        hovertemplate='%{y} failures<extra></extra>'
    ))

    fig.add_trace(go.Bar(
        x=models,
        y=successes,
        name='Successes',
        marker_color='green',
        hovertemplate='%{y} successes<extra></extra>'
    ))

    fig.update_layout(
        barmode='stack',
        title='Approach/LLM Failure and Success Rates to produce output',
        xaxis_title='LLM Models',
        yaxis_title='Number of Calls',
        legend_title='Outcome',
        template='plotly_white',
        hovermode='x unified'
    )
    return {"fig": fig, "html_explanation": ""}
def test_visualization(data):
    html_explanation = """
    <h2 style="text-align: center;">Total Credits awarded by each model on each submission</h2>
    """
    submission_ids = []
    approaches = []
    total_credits = []

    for submission_id, approaches_data in data.items():
        for approach, credits in approaches_data.items():
            submission_ids.append(submission_id)
            approaches.append(approach)
            total_credits.append(sum(credits))

    fig = px.bar(
        x=submission_ids,
        y=total_credits,
        color=approaches,
        barmode="group",
        title="Total Credits by Approach for Each Submission ID",
        labels={"x": "Submission ID", "y": "Total Credits", "color": "Approach"}
    )

    return {"fig": fig, "html_explanation": html_explanation}
    

def visualize_histogram_kde_percentages(credit_data,max_points):
    html_explanation = """ 
<h1 style="text-align: center; font-size: 32px;">Histogram of frequency of total credits given</h1>
<h2 style="text-align: center; font-size: 24px; color: #555;">Insights into Score Distribution</h2>
<p style="text-align: center; font-size: 18px; max-width: 800px; margin: 20px auto; line-height: 1.6;">
    Its just a histogram.
</p>

    """
    x = []
    group_labels = []
    approach_credits = {}
    for submission_id, approaches in credit_data.items():
        for approach, credits in approaches.items():
            if approach not in approach_credits:
                approach_credits[approach] = []
            if (sum(credits) > max_points):
                approach_credits[approach].append(max_points)
            else:
                approach_credits[approach].append(sum(credits)) # /max_points*100
    for approach, credits in approach_credits.items():
        x.append(credits)
        group_labels.append(approach)
    
    fig = go.Figure() 
    for approach, credits in approach_credits.items():
        fig.add_trace(go.Histogram(x=credits, name=approach,xbins=dict(size=0.5)))  
    fig.update_layout(
    title='Histogram of Total Credits Given',
    xaxis_title='Total Credits',
    yaxis_title='Count')
    fig.update_traces(opacity=0.7)
    return {"fig": fig, "html_explanation": html_explanation}  
    
def visualize_differences_histogram(credit_data,max_points):
    html_explanation = """
    <h1 style="text-align: center; font-size: 32px;">Distribution of Score Disparity Between LLM and Tutor</h1>
    <p style="text-align: center; font-size: 18px; max-width: 800px; margin: 20px auto; line-height: 1.6;">
        This graph represents the distribution of score differences between the LLM and the tutor. Negative values indicate 
        that the LLM has scored the submission lower than the tutor, while positive values suggest the opposite. 
    </p>
    <p style="text-align: center; font-size: 18px; max-width: 800px; margin: 20px auto; line-height: 1.6;">
        The chart provides insights into the consistency and bias of the LLM's grading compared to the tutor. Viewers 
        should look for patterns such as a strong concentration of values near zero, which would indicate agreement, or 
        significant skew towards negative or positive values, highlighting systematic under- or over-grading by the LLM.
    </p>
    <p style="text-align: center; font-size: 18px; max-width: 800px; margin: 20px auto; line-height: 1.6;">
        This visualization can help identify discrepancies and areas where the LLM may need calibration or adjustment 
        to align more closely with tutor assessments.
    </p>
    """
    differences_data = differences(credit_data)
        
    fig = go.Figure() 
    for approach, credits in differences_data.items():
        fig.add_trace(go.Histogram(x=credits, name=approach,xbins=dict(size=0.5)))  
    fig.update_layout(
    title='Histogram of differences',
    xaxis_title='Difference LLM - Tutor',
    yaxis_title='Count')
    fig.update_traces(opacity=0.8)
    return {"fig": fig, "html_explanation": html_explanation}

def normalized_absolute_difference(credits, max_points):
    """Plots the normalized absolute difference between the LLM and the other approaches in a sorted bar plot.

    Args:
        credits (dict): A dictionary with approaches and their score differences.
        max_points (float): Maximum possible credits for normalization.
    """
    differences_data = differences(credits)
    normalized_differences = {
        approach: sum(abs(d) for d in diff_list) / len(diff_list) / max_points
        for approach, diff_list in differences_data.items()
    }

    sorted_differences = dict(sorted(normalized_differences.items(), key=lambda x: x[1], reverse=True))

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=list(sorted_differences.keys()),
            y=list(sorted_differences.values()),
            marker_color='cornflowerblue'
        )
    )

    fig.update_layout(
        title='Normalized Absolute Differences Between LLM and Tutor Score',
        xaxis_title='Approaches',
        yaxis_title='Normalized Absolute Difference',
        xaxis={"categoryorder": 'total descending'},
        yaxis={"range": [0, 1]},
        template='plotly_white'
    )
    html_explanation = """ <h1 style="text-align: center;">Normalized Absolute Differences Between LLM and the Tutor</h1>
<p style="text-align: center; font-size: 18px; max-width: 800px; margin: 20px auto; line-height: 1.6;">
    This bar plot visualizes the <strong>normalized absolute differences</strong> in scores between the LLM and other approaches. 
    Each bar represents an approach, sorted from the highest to the lowest difference, and normalized by dividing the average 
    absolute difference by the maximum possible score.
</p>
<h2 style="text-align: center;">Insights: </h2>
<ul style="text-align: center;">
    <li style="text-align: center;font-size: 18px;"><strong>The height of each bar:</strong> Indicates how far, on average, the scores from a specific approach differ from the tutor's feedback after normalization.</li>
    <li style="text-align: center;font-size: 18px;"><strong>Lower values:</strong> Suggest better alignment with tutor feedback, reflecting higher agreement.</li>
    <li style="text-align: center;font-size: 18px;"><strong>Higher values:</strong> Indicate greater deviation, showing approaches that diverge more from tutor assessments.</li>
</ul>
<p style="text-align: center;">
    This visualization allows you to identify which approaches are the most and least consistent with tutor feedback, helping 
    analyze the effectiveness of LLM scoring.
</p>
<p style="text-align: center;" >
    <em>Note:</em> The data is normalized to allow fair comparisons across different scales of scores and different exercises.
</p>"""
    return {"fig": fig, "html_explanation": html_explanation}

def differences(credits):
    """ Calculates the literal differences between the tutor and the other approaches
    removes the submission id, but keeps the credit differences in order so that 
    values at index 0 are the same submission and so on.
    The calculation is LLM - Tutor, so a negative value means that the LLM has awarded less credits.
    The end form is :
    {approach: [differences], ...}
    """
    differences_data = {} 
    for submission_id, approaches in credits.items():
        for approach, credit_list in approaches.items():
            if approach != "Tutor":
                if approach not in differences_data:
                    differences_data[approach] = []
                differences_data[approach].append( sum(credit_list) - sum(approaches["Tutor"]))
    return differences_data

def getAbsoluteDifferences(differences):
    abs_diff = {}
    for approach, diff_list in differences.items():
        abs_diff[approach] = np.abs(diff_list)
    return abs_diff

def analyze_grading_instruction_usage(grading_instructions_used):
    """
    Analyze grading instruction usage for each approach and plot matching vs. non-matching counts.

    Parameters:
    - grading_instructions_used: dict, where keys are submission IDs, and values are dicts with approaches and lists of grading instruction IDs.

    Returns:
    - A Plotly figure object with analytics on matching vs. non-matching grading instruction IDs.
    - An HTML string explanation.
    """
    approach_stats = {}

    for submission_id, approaches in grading_instructions_used.items():
        if "Tutor" not in approaches:
            continue

        tutor_instructions = Counter(approaches["Tutor"])

        for approach, instructions in approaches.items():
            if approach == "Tutor":
                continue

            if approach not in approach_stats:
                approach_stats[approach] = {"matches": 0, "non_matches": 0}

            approach_instructions = Counter(instructions)

            matches = 0
            non_matches = 0

            for instruction, count in approach_instructions.items():
                if instruction in tutor_instructions:
                    matches += min(count, tutor_instructions[instruction])
                else:
                    non_matches += count

            approach_stats[approach]["matches"] += matches
            approach_stats[approach]["non_matches"] += non_matches

    approaches = list(approach_stats.keys())
    matches = [approach_stats[approach]["matches"] for approach in approaches]
    non_matches = [approach_stats[approach]["non_matches"] for approach in approaches]

    import plotly.graph_objects as go
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=approaches, y=matches, name="Matching Instructions",
        marker_color="green"
    ))
    fig.add_trace(go.Bar(
        x=approaches, y=non_matches, name="Non-Matching Instructions",
        marker_color="red"
    ))

    fig.update_layout(
        barmode="group",
        title="Matching vs. Non-Matching Grading Instructions by Approach",
        xaxis_title="Approach",
        yaxis_title="Count",
        template="plotly_white",
    )

    html_explanation = """
    <h1 style="text-align: center; font-size: 32px;">Grading Instruction Usage Analysis</h1>
    <p style="text-align: center; font-size: 18px; max-width: 800px; margin: 20px auto; line-height: 1.6;">
        This visualization compares the grading instructions used by different approaches
        against the "Tutor" approach. The green bars represent the count of grading instructions
        that match those of the Tutor approach, while the red bars show the count of non-matching
        instructions. This analysis highlights alignment and deviations between approaches.
    </p>
    """

    return fig, html_explanation

def create_threshold_bar_plot(data,max_points):
    thresholds = [0, 0.1, 0.15, 0.2, 0.25, 0.3]
    data_dicts = []
    for threshold in thresholds:
        data_dicts.append(percentage_within_range(data,max_points, threshold))
    fig = go.Figure()

    for approach in data_dicts[0].keys():
        fig.add_trace(go.Bar(
            name=approach,
            x=[f"{threshold*100}%" for threshold in thresholds],
            y=[data[approach] for data in data_dicts],
            text=[f"{v}%" for v in [data[approach] for data in data_dicts]],
            textposition='auto'
        ))

    fig.update_layout(
        title="Percentage of Counts Within Thresholds by Approach",
        xaxis_title="Thresholds",
        yaxis_title="Percentage (%)",
        barmode='group',
        legend_title="Approaches",
        template='plotly'
    )
    html_explanation = """
    <h1 style="text-align: center; font-size: 32px;">Percentage of LLM results, that fall within a range of maximum points difference from the tutor feedback</h1>
    <p style="text-align: center; font-size: 18px; max-width: 800px; margin: 20px auto; line-height: 1.6;">
        For example, for threshold 10 per cent. If the max points are 5, it only includes those llm results that are within 0.5 points of the tutor feedback. A bar of 20 per cent
        would translate to 20 per cent of the llm results being within 0.5 points of the tutor feedback.
    </p>
    """
    return {"fig": fig, "html_explanation": html_explanation}

def percentage_within_range(data,max_points , threshold):
    """ This method shows the percentage of the data that falls within a certain range difference of the maximum credits from the tutor
    Args:
        data (_type_): the credits data
    """
    approach_credits = {}
    for submission_id, approaches in data.items():
        for approach, credits in approaches.items():
            if approach not in approach_credits:
                approach_credits[approach] = []
            approach_credits[approach].append(sum(credits))
    
    results = {}
    tutor_credits = approach_credits["Tutor"]
    for approach,credit_total in approach_credits.items():
        if approach != "Tutor":
            if approach not in results:
                results[approach] = 0
            for idx,credit in enumerate(credit_total):
                within_range = calculate_within_cutoff(tutor_credits[idx], credit,max_points, threshold)
                if within_range:
                    results[approach] += 1
    for approach, count in results.items():
        results[approach] = round(count/len(tutor_credits)*100,2)
    return results
def calculate_within_cutoff(tutor_value, llm_value,max_points, threshold):
    upper_credit_cutoff = tutor_value + max_points * threshold
    lower_credit_cutoff = tutor_value - max_points * threshold
    within_range = llm_value <= upper_credit_cutoff and llm_value >= lower_credit_cutoff
    return within_range
