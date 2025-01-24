import pandas as pd
import plotly.express as px


def test_visualization(data):
    # Flatten the data for processing
    rows = []
    for submission_id, approaches in data.items():
        for approach, credits in approaches.items():
            rows.append({"submission_id": submission_id, "approach": approach, "total_credits": sum(credits)})

    # Create a DataFrame
    df = pd.DataFrame(rows)

    # Output DataFrame for verification
    print(df)
    
    # Create a bar chart
    fig = px.bar(
        df,
        x="submission_id",
        y="total_credits",
        color="approach",
        barmode="group",
        title="Total Credits by Approach for Each Submission ID",
        labels={"submission_id": "Submission ID", "total_credits": "Total Credits", "approach": "Approach"}
    )

    # Show the interactive chart
    # Export to an interactive HTML file
    fig.write_html("credits_comparison.html")