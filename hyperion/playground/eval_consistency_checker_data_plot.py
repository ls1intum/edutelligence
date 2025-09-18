#!/usr/bin/env python3
"""
Model Performance Plotter

This class loads model performance data from JSON and creates various plots
to analyze the relationship between input tokens and model accuracy.
"""

from collections import defaultdict
import json
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import pearsonr
from typing import Dict, List, Any, Tuple
import os


class ModelPerformancePlotter:
    def __init__(self, json_file_path: str):
        """Initialize plotter with data from JSON file."""
        self.json_file_path = json_file_path
        self.data = self._load_data()
        self.model_names = list(self.data.keys())

    def _load_data(self) -> Dict[str, List[Dict[str, Any]]]:
        """Load model performance data from JSON file.

        Expected format: {model_name:[runs]}
        {
            "o4-mini": [
                {
                    "variant": "001",
                    ...
                },
                ...
            ],
            ...
        }

        Each run result should contain: prompt_tokens, f1, exercise fields
        """
        if not os.path.isfile(self.json_file_path):
            raise FileNotFoundError(f"JSON file not found: {self.json_file_path}")
        try:
            with open(self.json_file_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            if not isinstance(data, dict):
                raise ValueError(
                    "JSON data must be a dictionary of model names to lists of runs."
                )
            return data
        except json.JSONDecodeError as e:
            raise ValueError(f"Error decoding JSON: {e}")

    def _filter_valid_runs(self, runs: List[Dict]) -> List[Dict]:
        """Filter out runs with invalid prompt_tokens (N/A or None) and extract data within a model.
        Input:
        runs = [
                {
                    ...
                },
                ...
            ]
        Returns: same as input but only valid runs, for a specific model
        This is the core data extraction for x-axis (input tokens) and y-axis (F1 scores)
        """
        return [
            run
            for run in runs
            if run.get("prompt_tokens") not in ["N/A", None]
            and run.get("f1") is not None
        ]

    def get_summary_statistics(self) -> Dict[str, Dict]:
        """Get summary statistics for each model."""
        summary = {}

        for model_name, runs in self.data.items():
            valid_runs = self._filter_valid_runs(runs)
            tokens, f1_scores = [], []
            if valid_runs:
                tokens = [run["prompt_tokens"] for run in valid_runs]
                f1_scores = [run["f1"] for run in valid_runs]

                summary[model_name] = {
                    "n_samples": len(tokens),
                    "avg_f1": np.mean(f1_scores),
                    "std_f1": np.std(f1_scores),
                    "avg_tokens": np.mean(tokens),
                    "std_tokens": np.std(tokens),
                    "min_f1": np.min(f1_scores),
                    "max_f1": np.max(f1_scores),
                    "correlation": (
                        pearsonr(tokens, f1_scores)[0] if len(tokens) > 1 else None
                    ),
                    "p_value": (
                        pearsonr(tokens, f1_scores)[1] if len(tokens) > 1 else None
                    ),
                }

        return summary

    def print_correlation_analysis(self):
        """Print correlation analysis table within each model.

        This calculates Pearson correlation between INPUT TOKENS (X) and F1 SCORES (Y).
        Negative correlation = more tokens hurt performance.
        """
        if not self.data:
            print("No model data available.")
            return

        print("Correlation Analysis: Input Tokens vs F1 Score")
        print("=" * 60)
        print(
            f"{'Model Name':<25} | {'Correlation':<11} | {'P-Value':<8} | {'N Samples':<9}"
        )
        print("-" * 60)

        for model_name, runs in self.data.items():
            valid_runs = self._filter_valid_runs(runs)  # X=tokens, Y=F1
            if (
                len(valid_runs) > 1
            ):  # for model correlation we need at least 2 data points
                tokens = [run["prompt_tokens"] for run in valid_runs]
                f1_scores = [run["f1"] for run in valid_runs]
                try:
                    corr, p_value = pearsonr(tokens, f1_scores)
                    if np.isnan(corr) or np.isnan(p_value):
                        print(
                            f"{model_name:<25} | {'Invalid':<11} | {'N/A':<8} | {len(tokens):<9}"
                        )
                    else:
                        significance = ""
                        if p_value < 0.001:
                            significance = "***"
                        elif p_value < 0.01:
                            significance = "**"
                        elif p_value < 0.05:
                            significance = "*"

                        print(
                            f"{model_name:<25} | {corr:8.3f}{significance:<3} | {p_value:8.3f} | {len(tokens):<9}"
                        )
                except Exception as e:
                    print(
                        f"{model_name:<25} | {'Error':<11} | {'N/A':<8} | {len(tokens):<9}"
                        + f" (Error: {e})"
                    )
            else:
                print(
                    f"{model_name:<25} | {'N/A':<11} | {'N/A':<8} | {len(valid_runs):<9}"
                )

        print("\nSignificance: *** p<0.001, ** p<0.01, * p<0.05")

    def print_per_exercise_correlation_analysis(self):
        """Print detailed correlation analysis by exercise within each model and grouped by exercise."""

        if not self.data:
            print("No model data available.")
            return

        print("Per-Exercise Correlation Analysis: Input Tokens vs F1 Score")
        print("=" * 80)
        print(
            f"{'Model':<25} | {'Exercise':<20} | {'Correlation':<11} | {'P-Value':<8} | {'N':<5}"
        )
        print("-" * 80)

        for model_name, runs in self.data.items():
            valid_runs = self._filter_valid_runs(runs)

            if not valid_runs:
                print(
                    f"{model_name:<25} | {'No valid data':<20} | {'N/A':<11} | {'N/A':<8} | {'0':<5}"
                )
                continue

            # Group by exercise
            model_data_all_ex = defaultdict(lambda: {"tokens": [], "f1_scores": []})
            for run in valid_runs:
                exercise = run.get("exercise", "unknown")
                model_data_all_ex[exercise]["tokens"].append(run["prompt_tokens"])
                model_data_all_ex[exercise]["f1_scores"].append(run["f1"])

            # Calculate correlation for each exercise
            for exercise, data in model_data_all_ex.items():
                tokens_exercise = data["tokens"]
                f1_exercise = data["f1_scores"]

                exercise_short_name = (
                    exercise.split("-")[0] if "-" in exercise else exercise[:20]
                )

                if len(tokens_exercise) > 1:
                    try:
                        corr, p_value = pearsonr(tokens_exercise, f1_exercise)
                        if np.isnan(corr) or np.isnan(p_value):
                            print(
                                f"{model_name:<25} | {exercise_short_name:<20} | {'Invalid':<11} | {'N/A':<8} | {len(tokens_exercise):<5}"
                            )
                        else:
                            significance = ""
                            if p_value < 0.001:
                                significance = "***"
                            elif p_value < 0.01:
                                significance = "**"
                            elif p_value < 0.05:
                                significance = "*"
                        print(
                            f"{model_name:<25} | {exercise_short_name:<20} | {corr:8.3f}{significance:<3} | {p_value:8.3f} | {len(tokens_exercise):<5}"
                        )
                    except Exception as e:
                        print(
                            f"{model_name:<25} | {exercise_short_name:<20} | {'Error':<11} | {'N/A':<8} | {len(tokens_exercise):<5}"
                            + f" (Error: {e})"
                        )
                else:
                    print(
                        f"{model_name:<25} | {exercise_short_name:<20} | {'N/A':<11} | {'N/A':<8} | {len(tokens_exercise):<5}"
                    )

            print("-" * 80)

        print("Significance: *** p<0.001, ** p<0.01, * p<0.05")
        print("\nInterpretation:")
        print("- This analysis controls for exercise complexity")
        print("- Shows pure input length effect WITHIN each exercise type")
        print("- Negative correlations suggest longer inputs hurt performance")

    def plot_per_model_subplots(
        self, save_path: str = None, color_by_exercise: bool = True
    ):
        """
        Plot per model for all exercises
        Creates separate subplots (one per model), with all exercises shown on each plot.
        Each exercise gets a different color within each model's subplot.

        Args:
            save_path: Path to save the plot
            color_by_exercise: Whether to color points by exercise type: true by default
        """
        if not self.data:
            print("No model data available for plotting.")
            return

        # Calculate optimal subplot layout dynamically
        n_models = len(self.model_names)
        if n_models == 1:
            cols, rows = 1, 1
        elif n_models <= 4:
            cols = 2
            rows = (n_models + 1) // 2
        else:  # 5+ models: use 3 columns
            cols = 3
            rows = (n_models + 2) // 3

        fig_width = 7 * cols
        fig_height = 5 * rows
        fig, axes = plt.subplots(rows, cols, figsize=(fig_width, fig_height))

        # Handle axes array structure (matplotlib returns different shapes)
        if n_models == 1:
            axes = [axes]
        else:
            axes = axes.flatten()  # Array (1D or 2D) → ensure 1D

        summary_stats = self.get_summary_statistics()

        all_exercises = (
            set()
        )  # all possible exercises in the data, model to model can derive
        for runs in self.data.values():
            for run in runs:
                if run.get("exercise"):
                    all_exercises.add(run["exercise"])

        exercise_colors = {}
        colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
        for i, exercise in enumerate(sorted(all_exercises)):
            exercise_colors[exercise] = colors[
                i % len(colors)
            ]  # Cycle through colors if many exercises

        for i, (model_name, runs) in enumerate(self.data.items()):
            if i >= len(axes):
                break

            axe = axes[i]
            valid_runs = self._filter_valid_runs(runs)

            if not valid_runs:
                axe.text(
                    0.5,
                    0.5,
                    "No valid data",
                    ha="center",
                    va="center",
                    transform=axe.transAxes,
                    fontsize=12,
                )  # Use axes coordinates (0-1)
                axe.set_title(model_name, fontsize=12)
                self._format_subplot(axe)  # consistent formatting
                continue

            tokens, f1_scores = [], []
            model_data_all_ex = defaultdict(lambda: {"tokens": [], "f1_scores": []})
            for run in valid_runs:
                token = run["prompt_tokens"]
                f1 = run["f1"]

                tokens.append(token)
                f1_scores.append(f1)
                exercise = run.get("exercise", "Unknown")
                model_data_all_ex[exercise]["tokens"].append(token)
                model_data_all_ex[exercise]["f1_scores"].append(f1)

            # Plot data points colored by exercise with different markers to avoid overlap
            if color_by_exercise and exercise_colors:
                # Plot each exercise group directly
                for exercise, data in model_data_all_ex.items():
                    ex_tokens = data["tokens"]
                    ex_f1 = data["f1_scores"]

                    if ex_tokens:
                        color = exercise_colors.get(exercise, "#999999")
                        label = (
                            exercise.split("-")[0] if "-" in exercise else exercise[:10]
                        )
                        axe.scatter(
                            ex_tokens,
                            ex_f1,
                            c=color,
                            alpha=0.7,
                            s=50,  # scatter plot (alpha = 0.8?)
                            label=label,
                            edgecolors="white",
                            linewidth=0.5,
                        )

                # Add points color explanation if space allows
                if len(all_exercises) <= 5:
                    axe.legend(
                        bbox_to_anchor=(1.05, 1), loc="upper left", frameon=False
                    )  # outside plot area
            else:
                # Plot all points in same color
                axe.scatter(
                    tokens,
                    f1_scores,
                    c="#1f77b4",
                    alpha=0.7,
                    s=50,
                    edgecolors="white",
                    linewidth=0.5,
                )

            # OLS Trend Line
            if len(tokens) > 1:
                try:
                    z = np.polyfit(
                        tokens, f1_scores, 1
                    )  # linear regression e.g [-0.0002, 1.1] - slope and intercept
                    p = np.poly1d(
                        z
                    )  # polynomial function  y=-0.0002x + 1.1, p is a function from x (token), which returns y (F1)
                    x_trend = np.linspace(
                        min(tokens), max(tokens), 100
                    )  # generates 100 points between min and max tokens
                    axe.plot(x_trend, p(x_trend), "r--", alpha=0.8, linewidth=2)
                except np.RankWarning:
                    pass

            # plot title
            stats = summary_stats.get(model_name, {})
            corr = stats.get("correlation")
            p_value = stats.get("p_value")
            n_samples = len(tokens)

            if corr is not None and not np.isnan(corr):
                title = f"{model_name}\nr={corr:.3f}, (p={p_value:.3f}), n={n_samples}"
            else:
                title = f"{model_name}\nn={n_samples}"

            axe.set_title(title, fontsize=11, fontweight="bold")
            self._format_subplot(axe)
        # Hide unused subplots
        for i in range(n_models, len(axes)):
            axes[i].set_visible(False)

        # Add overall title and finalize
        # plt.suptitle('Dependency Graph: Prompt Input Tokens and Accuracy (F1 Value)\n(Grouped by Model)',
        #            fontsize=14, fontweight='bold')
        plt.tight_layout()  # adjust spacing automatically

        # Save and show
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches="tight", facecolor="white")
            print(f"Plot saved to: {save_path}")
        plt.show()

    def _format_subplot(self, axe):
        """Helper function to apply consistent subplot formatting."""
        axe.set_xlabel("Input Tokens", fontsize=10)
        axe.set_ylabel("F1 Score", fontsize=10)
        axe.set_ylim(-0.05, 1.05)  # Y-axis range (F1 is 0-1)
        axe.grid(True, alpha=0.3)  # light grid
        axe.spines["top"].set_visible(False)  # remove top border
        axe.spines["right"].set_visible(False)  # remove right border

    def plot_per_model_per_exercise_subplots(self, save_path: str = None):
        """
        Plot per model and per exercise (grid format)
        Creates a grid where:
        - Each row = one model
        - Each column = one exercise

        Args:
            save_path: Path to save the plot
        """
        if not self.data:
            print("No model data available for plotting.")
            return
        # Discover all unique exercises in the data
        all_exercises = set()
        for runs in self.data.values():
            for run in runs:
                if run.get("exercise"):
                    all_exercises.add(run["exercise"])

        if not all_exercises:
            print("No exercises found in data.")
            return
        # print(f"Found exercises in data: {sorted(all_exercises)}")

        # Sort exercises to ensure consistent column order across different runs
        # Without sorting, exercise order could change randomly, making grid layout confusing
        exercise_list = sorted(all_exercises)
        n_models = len(self.model_names)
        n_exercises = len(exercise_list)

        exercise_colors = {}
        colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
        for i, exercise in enumerate(exercise_list):
            exercise_colors[exercise] = colors[i % len(colors)]

        fig, axes = plt.subplots(
            n_models, n_exercises, figsize=(4 * n_exercises, 3 * n_models)
        )  # 4 inches width per exercise, 3 inches height per model

        # matplotlib returns different formats depending on grid size -> We need consistent 2D access: axes[row][col] for all cases
        if n_models == 1 and n_exercises == 1:
            axes = [[axes]]
        elif n_models == 1:
            axes = [axes]
        elif n_exercises == 1:  # 1D array [ax1, ax2]
            axes = [[axe] for axe in axes]  # [[ax1], [ax2]] for axes[i][0]
        # else: already 2D array, no conversion needed

        # Process each model (each row of the grid)
        for i, (model_name, runs) in enumerate(self.data.items()):
            valid_runs = self._filter_valid_runs(runs)  # valid runs for this model

            if not valid_runs:
                for j, exercise in enumerate(exercise_list):
                    axe = axes[i][j]  # → Access as axes[row][column]
                    axe.text(
                        0.5,
                        0.5,
                        "No valid data",
                        ha="center",
                        va="center",
                        transform=axe.transAxes,
                        fontsize=12,
                    )
                    exercise_short_name = (
                        exercise.split("-")[0] if "-" in exercise else exercise[:10]
                    )
                    axe.set_title(f"{model_name}\n{exercise_short_name}", fontsize=10)
                    self._format_subplot(axe)
                continue

            model_data_all_ex = defaultdict(lambda: {"tokens": [], "f1_scores": []})
            for run in valid_runs:
                exercise = run.get("exercise", "Unknown")
                model_data_all_ex[exercise]["tokens"].append(run["prompt_tokens"])
                model_data_all_ex[exercise]["f1_scores"].append(run["f1"])

            # print(f"Model {model_name} has data for exercises: {list(exercise_data.keys())}")

            for j, exercise in enumerate(exercise_list):
                axe = axes[i][j]
                exercise_short_name = (
                    exercise.split("-")[0] if "-" in exercise else exercise[:10]
                )

                if exercise in model_data_all_ex:
                    ex_tokens = model_data_all_ex[exercise]["tokens"]
                    ex_f1 = model_data_all_ex[exercise]["f1_scores"]

                    if ex_tokens:
                        color = exercise_colors.get(exercise, "#999999")
                        axe.scatter(
                            ex_tokens,
                            ex_f1,
                            c=color,
                            alpha=0.7,
                            s=50,
                            edgecolors="white",
                            linewidth=0.5,
                        )

                        # OLS Trend Line
                        if len(ex_tokens) > 1:
                            try:
                                z = np.polyfit(ex_tokens, ex_f1, 1)
                                p = np.poly1d(z)
                                x_trend = np.linspace(
                                    min(ex_tokens), max(ex_tokens), 100
                                )
                                axe.plot(
                                    x_trend, p(x_trend), "r--", alpha=0.8, linewidth=2
                                )
                            except np.RankWarning:
                                pass

                        if len(ex_tokens) > 1:
                            try:
                                corr, p_value = pearsonr(ex_tokens, ex_f1)

                                significance = ""
                                if not np.isnan(p_value):
                                    if p_value < 0.001:
                                        significance = "***"
                                    elif p_value < 0.01:
                                        significance = "**"
                                    elif p_value < 0.05:
                                        significance = "*"

                                title = f"{model_name}\n{exercise_short_name}\nr={corr:.3f}{significance}, (p={p_value:.3f})\nn={len(ex_tokens)}"
                            except Exception:
                                # Fallback to simple title if correlation fails
                                title = f"{model_name}\n{exercise_short_name}\nn={len(ex_tokens)}"
                        else:
                            # Not enough data for correlation
                            title = f"{model_name}\n{exercise_short_name}\nn={len(ex_tokens)}"
                    else:
                        title = f"{model_name}\n{exercise_short_name}\nNo data"
                        axe.text(
                            0.5,
                            0.5,
                            "No data",
                            ha="center",
                            va="center",
                            transform=axe.transAxes,
                            fontsize=8,
                        )
                else:
                    title = f"{model_name}\n{exercise_short_name}\nNo data"
                    axe.text(
                        0.5,
                        0.5,
                        "No data",
                        ha="center",
                        va="center",
                        transform=axe.transAxes,
                        fontsize=8,
                    )

                axe.set_title(title, fontsize=9, fontweight="bold")
                self._format_subplot(axe)

        # Add overall title for the entire grid
        # plt.suptitle('Dependency Graph: Prompt Input Tokens and Accuracy (F1 Value) \n(Grouped by Model and Subgrouped by Exercise)',
        #            fontsize=14, fontweight='bold')
        plt.tight_layout()

        # Save plot if path provided
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches="tight")
            print(f"Matrix plot saved to: {save_path}")
        plt.show()


if __name__ == "__main__":
    # Create plotter instance - loads model_performance_results.json
    # Expected JSON format: {model_name: [{prompt_tokens: X, f1: Y, exercise: Z}, ...]}

    plotter = ModelPerformancePlotter("model_performance_results.json")

    # print("Summary Statistics:", plotter.get_summary_statistics())
    plotter.print_correlation_analysis()
    plotter.print_per_exercise_correlation_analysis()
    plotter.plot_per_model_subplots("plots/per_model.png")
    plotter.plot_per_model_per_exercise_subplots("plots/per_model_per_exercise.png")
