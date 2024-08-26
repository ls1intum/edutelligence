import numpy as np
import pandas as pd
from IPython.display import display, HTML
from matplotlib import pyplot as plt

from module_text_llm.text_evaluation.data_util import find_exercise_submission


def display_exercise_summaries(exercises, max_rows=None):
    """Displays summaries of exercises, submissions, and feedbacks."""

    def sample_with_equal_spacing(df, max_rows):
        return df.iloc[np.linspace(0, len(df) - 1, max_rows, dtype=int)] if max_rows and max_rows < len(df) else df

    # Create DataFrames using list comprehensions
    exercise_df = pd.DataFrame([{
        'Exercise ID': ex.id, 'Title': ex.title, 'Type': ex.type,
        'Max Points': ex.max_points, 'Bonus Points': ex.bonus_points,
        'Problem Statement': ex.problem_statement
    } for ex in exercises])

    submission_df = pd.DataFrame([{
        'Submission ID': sub.id, 'Exercise ID': ex.id, 'Language': sub.language,
        'Text': sub.text
    } for ex in exercises for sub in ex.submissions])

    feedback_df = pd.DataFrame([{
        'Submission ID': sub.id, 'Exercise ID': ex.id,
        'Feedback Type': fb_type, 'Number of Feedbacks': len(fbs)
    } for ex in exercises for sub in ex.submissions for fb_type, fbs in sub.feedbacks.items()])

    # Sample rows if max_rows is specified
    if max_rows:
        exercise_df, submission_df, feedback_df = map(lambda df: sample_with_equal_spacing(df, max_rows),
                                                      [exercise_df, submission_df, feedback_df])

    # Display the DataFrames with headings
    for title, df in zip(["Exercises", "Submissions", "Feedback Summary"], [exercise_df, submission_df, feedback_df]):
        display(HTML(f"<h3>{title}</h3>"))
        display(df)


def print_feedbacks(exercises, exercise_id_to_find=None, submission_id_to_find=None):
    """Prints a nicely formatted representation of key feedback details for the given exercise and submission."""

    exercise, submission = find_exercise_submission(exercises, exercise_id_to_find, submission_id_to_find)

    if not exercise or not submission:
        display(HTML(
            f"<div style='color: red; font-weight: bold;'>Error: {'Exercise' if not exercise else 'Submission'} not found.</div>"))
        return

    feedback_output = f"""
        <div><b>Exercise ID:</b> {exercise.id}</div>
        <div><b>Submission ID:</b> {submission.id}</div>
        <div><b>Feedbacks:</b><ul>
    """
    for feedback_type, feedbacks in submission.feedbacks.items():
        feedback_output += f"<li><b>{feedback_type} Feedback:</b><ul>"
        feedback_output += "".join(f"""
            <li>
                <b>Title:</b> {feedback.title}<br>
                <b>Description:</b> {feedback.description}<br>
                <b>Index Start:</b> {feedback.index_start}<br>
                <b>Index End:</b> {feedback.index_end}<br>
                <b>Credits:</b> {feedback.credits}<br>
            </li>
        """ for feedback in feedbacks)
        feedback_output += "</ul></li>"

    feedback_output += "</ul></div>"
    display(HTML(feedback_output))


def plot_top_logprobs(logprobs, selected_token, show_logprob=True, show_prob=True, highlight_selected=True, rotate_labels=True):
    tokens = [item['token'] for item in logprobs]
    logprob_values = [item['logprob'] for item in logprobs]
    probs = np.exp(logprob_values)

    highlight_index = tokens.index(selected_token) if highlight_selected and selected_token in tokens else -1
    colors = ['orange' if i == highlight_index else 'skyblue' for i in range(len(tokens))]

    tokens_display = [f"'{token}'" for token in tokens]
    num_plots = sum([show_logprob, show_prob])

    plt.figure(figsize=(max(5, len(tokens) / 2) * (2 if num_plots == 2 else 1), 4 if rotate_labels else 3))

    def plot_data(data, subplot_index, ylabel, title):
        plt.subplot(1, num_plots, subplot_index)
        plt.bar(tokens_display, data, color=colors)
        plt.xlabel('Tokens')
        if rotate_labels: plt.xticks()
        plt.ylabel(ylabel)
        plt.title(title)

    if show_logprob:
        plot_data(logprob_values, 1, 'Log Probability', 'Log Probabilities of Tokens')
    if show_prob:
        plot_data(probs, 2 if show_logprob else 1, 'Probability', 'Exponentiated Log Probabilities of Tokens')

    plt.tight_layout()
    plt.show()
