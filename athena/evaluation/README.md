# Evaluation Scripts

This directory contains a collection of Jupyter notebooks that support both expert and LLM-as-a-Judge evaluations for feedback generation.

The goal is to simplify the expert evaluation process by defining clear metrics and collecting human feedback in a standardized format. This enables consistent comparison across different feedback generation methods. While human evaluation is the primary focus, the notebooks also prepare for automated evaluation using a LLM as a judge.

## Directory Structure

- `data/`:  Stores CSV and JSON files used within the Jupyter notebooks
- `model/`: Contains classes that define the evaluation model
- `prompts/`: Includes prompt and metric templates for the LLM-as-a-Judge evaluation (see section 5: LLM-as-a-Judge)
- `service/`: Houses reusable service components utilized across notebooks
- `*.ipynb`: Jupyter notebooks to be executed in numerical order

## Prerequisites
**Before executing any notebooks**, ensure these requirements are met:
- Docker running
- Configured `.env` file (copy from `.env.example`)
- SQL dump file in the directory `data/0_db_dump`
- Playground running for Feedback generation (step 3), Expert evaluation setup (step 4)
- Azure OpenAI Service credentials for LLM-as-Judge evaluation (step 5)

## Notebooks Overview
Below is a short overview of the notebooks to be executed:

### 0. Database Setup (`0_database_setup.ipynb`)

- Initializes MySQL container
- Restores initial dataset
- Runtime: multiple minutes


### 1. Sampling Exercises (`1_sampling_exercises.ipynb`)

- Samples specific exercises using manual ID selection
- Filter out missing or invalid data
- Removes non-English texts

**Notes:**
- Standardized CSV output saved in: `data/1_exercises/exercises.csv`
- Manual step: Edit the variable `EXERCISE_IDS` set with your target exercise IDs
    ```python
        EXERCISE_IDS = {4066, 642, 544, 506}  # Replace with your IDs
    ```
- Subsequent runs can comment out saving cell and use pd.read_csv()
- LangID filtering (~95% accuracy) - manual verification recommended
  

### 2. Sampling Submissions (`2_sampling_submissions.ipynb`)

- Uses random sampling to obtain a representative sample of submissions for each exercise
- Sampling is replicate by using a random seed 
- Generates JSON and CSV representations of the sampled submissions

**Notes:**
- Output paths: `data/2_submissions/submissions.csv`, `data/2_submissions/json_files/`
- Manual step: Edit the directory `EXERCISE_SAMPLES` to specify the number of samples for each exercise
    ```python
        EXERCISE_SAMPLES = {4066: 25, 642: 25, 544: 25, 506: 25}  # Replace with your exercise IDs and sample sizes
    ```
- JSON structure optimized for Athena evaluation framework


### 3. Generating Feedback (`3_feedback_generation.ipynb`)

- Merges playground-generated feedback with submissions
- Prepares final evaluation dataset

**Playground Manual Step:** Generate missing feedback types used in the evaluation.
There might be feedback types such as LLM-generated feedback, which has not included in the dump file. 
In this case the feedback can be generated in the Playground
1. Access the Playground > Evaluation Mode
2. Define a new Experiment
3. Upload JSON files from previous step
4. Generate missing feedback types
5. Export the generated feedback JSONS 
6. Save files in the `data/3_feedback_suggestions/feedback_suggestions` directory

**Notes:**
- Output paths: `data/3_feedback_suggestions/feedback_suggestions.csv`, `data/3_feedback_suggestions/json_files/`
- Exported feedback file naming convention: `text_results_<Configuration Name>_<...>.json`
- The configuration names for feedback generation should not contain underscores '_'
- The configuration names should be unique for different feedback types but the same across different exercises
- Automatic fallback to tutor feedback (feedback in the dump file)  in case no feedback has been generated


### 4. Expert Evaluation (`4_expert_evaluation.ipynb`)

- Consolidates expert evaluation data
- Prepares final analysis dataset

**Playground Manual Step:** Perform expert evaluation in playground.
1. Access the Playground > Evaluation Mode
2. Create a new Expert Evaluation by importing the JSON files from the previous step
3. Define metrics, create a link for each expert and start the expert evaluation
4. After the evaluation has been completed, export the progress files
5. Save the downloaded files to `data/4_expert_evaluation`

**Notes:**
- Expert Evaluation Output path: `data/4_expert_evaluation/expert_evaluation.csv`
- Preserve original playground export filenames
- Single CSV output combines all evaluation sessions


### 5. LLM-as-a-Judge (`5_llm_as_a_judge.ipynb`)

- Conducts an evaluation where a LLM is used in state of a expert to evaluate feedback based on defined metrics
- Measures feedback quality across metrics
- Generates comparative analysis dataset

**Notes:**
- LLM Evaluation Output path: `data/5_llm_evaluation/llm_evaluations.csv`
- Possible Manual step: Define own evaluation metrics in `prompts/metrics.py`. Alternatively, use the pre-existing ones.
- Metrics must match expert evaluation criteria for comparison
- Possible to test out different prompts


## Execution Instructions
1. Verify all prerequisites
2. Start Jupyter server
3. Run notebooks in numerical order
4. Check for success messages after each notebook
5. Monitor Azure costs during Notebook 5