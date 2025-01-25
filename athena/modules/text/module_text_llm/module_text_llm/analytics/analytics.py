import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.figure_factory as ff
import numpy as np

def test_visualization(data):
    html_explanation = """
    <h2 style="text-align: center;">Total Credits awarded by each model on each submission</h2>
    """
    rows = []
    for submission_id, approaches in data.items():
        for approach, credits in approaches.items():
            rows.append({"submission_id": submission_id, "approach": approach, "total_credits": sum(credits)})

    df = pd.DataFrame(rows)
    fig = px.bar(
        df,
        x="submission_id",
        y="total_credits",
        color="approach",
        barmode="group",
        title="Total Credits by Approach for Each Submission ID",
        labels={"submission_id": "Submission ID", "total_credits": "Total Credits", "approach": "Approach"}
    )
    return {"fig": fig, "html_explanation": html_explanation}
    

def visualize_histogram_kde_percentages(credits,max_points):
    html_explanation = """ 
<h1 style="text-align: center; font-size: 32px;">Distribution of Score Percentages Awarded by LLM and Tutor</h1>
<h2 style="text-align: center; font-size: 24px; color: #555;">Insights into Assessment Skew and Distribution Comparison</h2>
<p style="text-align: center; font-size: 18px; max-width: 800px; margin: 20px auto; line-height: 1.6;">
    This graph illustrates the distribution of score percentages awarded by the LLM and the tutor. 
    It provides valuable information on the skew of the assessments and allows for a direct comparison 
    of their distributions. The plot is a smoothed Kernel Density Estimate (KDE), a non-parametric method 
    for visualizing a distribution without assuming any specific underlying model.
</p>

    """
    x = []
    group_labels = []
    approach_credits = {}
    for submission_id, approaches in credits.items():
        for approach, credits in approaches.items():
            if approach not in approach_credits:
                approach_credits[approach] = []
            approach_credits[approach].append(sum(credits)/max_points*100)
    for approach, credits in approach_credits.items():
        x.append(credits)
        group_labels.append(approach)
            
    fig = ff.create_distplot(x, group_labels, bin_size=0.5)
    fig.update_layout(
    title='Distribution of Score Percentages',
    xaxis_title='Percentage of Maximum Credits',
    yaxis_title='Density**')
    fig.add_annotation(
    text="** Density referes to the estimated probability density of the data at each X-axis value by the KDE smoothing, intuitively its like frequency",
    x=0, y=-0.2,  # Position below the plot
    showarrow=False,
    font=dict(size=12, color="gray"),
    align="center")
    return {"fig": fig, "html_explanation": html_explanation}       
def visualize_differences_histogram(credits,max_points):
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
    differences_data = differences(credits)
    x = [] 
    group_labels = [] 
    for approach, credits in differences_data.items():
        x.append(credits)
        group_labels.append(approach)
    fig = ff.create_distplot(x, group_labels, bin_size=0.5)
    fig.update_layout(
    title='Distribution of Score Differences',
    xaxis_title='Score Difference (LLM - Tutor)',
    yaxis_title='Density**')
    
    fig.add_annotation(
    text="** Density referes to the estimated probability density of the data at each X-axis value by the KDE smoothing, intuitively its like frequency",
    x=0, y=-0.2,  # Position below the plot
    showarrow=False,
    font=dict(size=12, color="gray"),
    align="center")

    return {"fig": fig, "html_explanation": html_explanation}

def normalized_absolute_difference(credits, max_points):
    """Plots the normalized absolute difference between the LLM and the other approaches in a sorted bar plot.

    Args:
        credits (dict): A dictionary with approaches and their score differences.
        max_points (float): Maximum possible credits for normalization.
    """
    # Calculate absolute differences and normalize
    differences_data = differences(credits)  # Returns {approach: [differences], ...}
    normalized_differences = {
        approach: sum(abs(d) for d in diff_list) / len(diff_list) / max_points
        for approach, diff_list in differences_data.items()
    }

    # Sort by normalized difference
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
        xaxis=dict(categoryorder='total descending'),  # Sort bars
        yaxis=dict(range=[0, 1]),  # Normalized values between 0 and 1
        template='plotly_white'
    )
    html_explanation = f""" <h1 style="text-align: center;">Normalized Absolute Differences Between LLM and the Tutor</h1>
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

def differences(credits:dict) -> dict:
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
    # Initialize data structures
    approach_stats = {}

    for submission_id, approaches in grading_instructions_used.items():
        if "Tutor" not in approaches:
            continue
        tutor_instructions = set(approaches["Tutor"])

        for approach, instructions in approaches.items():
            if approach == "Tutor":
                continue

            if approach not in approach_stats:
                approach_stats[approach] = {"matches": 0, "non_matches": 0}

            # Calculate matching and non-matching grading instructions
            approach_instructions = set(instructions)
            matches = tutor_instructions.intersection(approach_instructions)
            non_matches = approach_instructions - tutor_instructions

            approach_stats[approach]["matches"] += len(matches)
            approach_stats[approach]["non_matches"] += len(non_matches)

    # Prepare data for plotting
    approaches = list(approach_stats.keys())
    matches = [approach_stats[approach]["matches"] for approach in approaches]
    non_matches = [approach_stats[approach]["non_matches"] for approach in approaches]

    # Create bar plot
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=approaches, y=matches, name="Matching Instructions",
        marker_color="green"
    ))
    fig.add_trace(go.Bar(
        x=approaches, y=non_matches, name="Non-Matching Instructions",
        marker_color="red"
    ))

    # Update layout
    fig.update_layout(
        barmode="group",
        title="Matching vs. Non-Matching Grading Instructions by Approach",
        xaxis_title="Approach",
        yaxis_title="Count",
        template="plotly_white",
    )

    # HTML explanation
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