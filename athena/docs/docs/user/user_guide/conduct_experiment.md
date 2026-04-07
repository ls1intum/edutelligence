---
title: Conducting an Experiment
---

To conduct an experiment in the Athena Playground, follow these steps:

1.  **Define Experiment:**  
    - Scroll to the Evaluation Mode section.
    - In "Define Experiments", choose execution modes, exercise types,
      and manage training and evaluation data.
    - Alternatively, import an experiment configuration using the
      "Import" button.
    - When done, press "Define Experiment".
    - Export the experiment configuration using the "Export" button for
      future reference.

  ![Evaluation Mode: Define Experiment Interface of the Athena
  Playground](/img/playground/evaluation_mode/define_experiment.png)

2.  **Configure Modules:**  
    - Select and configure the modules you wish to include in your
      experiment.
    - Ensure each module is set up with appropriate parameters for
      effective comparison.
    - Import module configurations using the "Import" button, if needed.
    - Export the module configurations using the "Export" button for
      future reference.

  ![Evaluation Mode: Configure Modules Interface of the Athena
  Playground](/img/playground/evaluation_mode/configure_modules.png)

3.  **Conduct Experiment:**  
    - Press "Start Experiment" to begin the experiment.
    - The steps performed include sending submissions, sending feedback
      for training submissions, generating feedback suggestions, and
      running automatic evaluations.
    - If training submissions are provided, you will need to manually
      continue the experiment by pressing "Continue".
    - If automatic evaluation is enabled, for instance LLM-as-a-judge
      for text exercises, you will also need to manually confirm it.
    - Export and import the experiment results as needed using the
      "Export" and "Import" buttons, respectively.

  <figure>
  <img
  src="/img/playground/evaluation_mode/conduct_experiment_text.png"
    width="500"
    alt="Conduct Experiment Interface for a Text Exercise of the Athena Playground" />
    <figcaption>Evaluation Mode: Conduct Experiment Interface for a Text
    Exercise of the Athena Playground</figcaption>
    </figure>

4.  **Annotate Feedback Suggestions:**  
    - Annotate the generated feedback suggestions with "Accept" or
      "Reject" as a tutor would.

5.  **Export Results:**  
    - At the end of the experiment, or at any time during the
      experiment, export the results using the "Export" button.
    - Make sure that you also exported the experiment configuration and
      module configurations to have a complete record of the experiment.
