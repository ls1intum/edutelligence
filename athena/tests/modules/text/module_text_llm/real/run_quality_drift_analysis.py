#!/usr/bin/env python3
"""
Quality Drift Analysis Runner

This script:
1. Generates baseline feedbacks using GPT-4o for exercise 7 (only if needed)
2. Runs quality drift analysis tests comparing ALL models against the baseline
3. Produces comprehensive reports and metrics

All in one self-contained script!
"""

import asyncio
import json
import sys
import os
import random
from pathlib import Path
from typing import Dict, Any, List
import time
from datetime import datetime
import numpy as np
from bert_score import score as bert_score

# Thresholds for pass/fail
MIN_BERTSCORE_F1 = 0.80
MAX_MEAN_CREDIT_DRIFT = 3.0

# Import required modules
from athena.text import Exercise, Submission
from athena.schemas.exercise_type import ExerciseType
from athena.schemas.text_submission import TextLanguageEnum
from module_text_llm.default_approach.generate_suggestions import generate_suggestions
from module_text_llm.default_approach import DefaultApproachConfig
from llm_core.models.providers.azure_model_config import AzureModelConfig
from conftest import get_model_configs


class QualityDriftAnalyzer:
    """Analyzes quality drift between different LLM models using BERTScore."""
    
    def __init__(self):
        self.baseline_feedbacks = {}
        self.test_feedbacks = {}
        self.baseline_info = {}
        
    def load_baseline_feedbacks(self, exercise_data_path: str):
        """Load baseline feedbacks from exercise-7.json."""
        with open(exercise_data_path, 'r', encoding='utf-8') as f:
            exercise_data = json.load(f)
        
        # Load baseline info
        self.baseline_info = exercise_data.get("baseline_info", {})
        
        for submission in exercise_data["submissions"]:
            submission_id = submission["id"]
            # Skip submissions without baseline feedbacks
            if "feedbacks" not in submission:
                continue
            baseline_feedbacks = []
            for feedback in submission["feedbacks"]:
                baseline_feedbacks.append({
                    "description": feedback["description"],
                    "title": feedback["title"],
                    "credits": feedback["credits"]
                })
            self.baseline_feedbacks[submission_id] = baseline_feedbacks
    
    async def generate_test_feedbacks(self, config: DefaultApproachConfig, exercise: Exercise, submission: Submission):
        """Generate feedbacks using the test model."""
        feedbacks = await generate_suggestions(
            exercise=exercise,
            submission=submission,
            config=config,
            debug=False,
            is_graded=True,
            learner_profile=None,
        )
        
        test_feedbacks = []
        for feedback in feedbacks:
            test_feedbacks.append({
                "description": feedback.description,
                "title": feedback.title,
                "credits": feedback.credits
            })
        
        return test_feedbacks
    
    def calculate_bertscore_similarity(self, baseline_texts: List[str], test_texts: List[str]) -> Dict[str, float]:
        """Calculate BERTScore similarity between baseline and test feedbacks."""
        if not baseline_texts or not test_texts:
            return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
        
        # Filter out empty strings and ensure we have valid texts
        baseline_texts_filtered = [text.strip() for text in baseline_texts if text.strip()]
        test_texts_filtered = [text.strip() for text in test_texts if text.strip()]
        
        if not baseline_texts_filtered or not test_texts_filtered:
            return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
        
        # Use the minimum length to avoid padding issues
        min_len = min(len(baseline_texts_filtered), len(test_texts_filtered))
        baseline_texts_trimmed = baseline_texts_filtered[:min_len]
        test_texts_trimmed = test_texts_filtered[:min_len]
        
        try:
            precision, recall, f1 = bert_score(
                test_texts_trimmed, 
                baseline_texts_trimmed, 
                lang='en', 
                verbose=False
            )
            
            # Convert to numpy arrays and handle the mean calculation properly
            precision_np = precision.cpu().numpy() if hasattr(precision, 'cpu') else np.array(precision)
            recall_np = recall.cpu().numpy() if hasattr(recall, 'cpu') else np.array(recall)
            f1_np = f1.cpu().numpy() if hasattr(f1, 'cpu') else np.array(f1)
            
            return {
                "precision": float(np.mean(precision_np)),
                "recall": float(np.mean(recall_np)),
                "f1": float(np.mean(f1_np))
            }
        except Exception as e:
            print(f"BERTScore calculation failed: {e}")
            return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    
    def calculate_credit_drift(self, baseline_feedbacks: List[Dict], test_feedbacks: List[Dict]) -> Dict[str, float]:
        """Calculate credit drift between baseline and test feedbacks."""
        if not baseline_feedbacks or not test_feedbacks:
            return {"mean_drift": 0.0, "std_drift": 0.0, "max_drift": 0.0}
        
        baseline_credits = [feedback["credits"] for feedback in baseline_feedbacks]
        test_credits = [feedback["credits"] for feedback in test_feedbacks]
        
        # Use the minimum length to avoid padding issues
        min_len = min(len(baseline_credits), len(test_credits))
        baseline_credits_trimmed = baseline_credits[:min_len]
        test_credits_trimmed = test_credits[:min_len]
        
        differences = [abs(b - t) for b, t in zip(baseline_credits_trimmed, test_credits_trimmed)]
        
        if not differences:
            return {"mean_drift": 0.0, "std_drift": 0.0, "max_drift": 0.0}
        
        return {
            "mean_drift": float(np.mean(differences)),
            "std_drift": float(np.std(differences)),
            "max_drift": float(np.max(differences))
        }
    
    def analyze_quality_drift(self, submission_id: int) -> Dict[str, Any]:
        """Analyze quality drift for a specific submission."""
        baseline_feedbacks = self.baseline_feedbacks.get(submission_id, [])
        test_feedbacks = self.test_feedbacks.get(submission_id, [])
        
        if not baseline_feedbacks or not test_feedbacks:
            return {
                "bertscore": {"precision": 0.0, "recall": 0.0, "f1": 0.0},
                "credit_drift": {"mean_drift": 0.0, "std_drift": 0.0, "max_drift": 0.0}
            }
        
        # Calculate BERTScore similarity
        baseline_texts = [f"{f['title']} {f['description']}" for f in baseline_feedbacks]
        test_texts = [f"{f['title']} {f['description']}" for f in test_feedbacks]
        bertscore_result = self.calculate_bertscore_similarity(baseline_texts, test_texts)
        
        # Calculate credit drift
        credit_drift_result = self.calculate_credit_drift(baseline_feedbacks, test_feedbacks)
        
        return {
            "bertscore": bertscore_result,
            "credit_drift": credit_drift_result
        }


class QualityDriftAnalysisRunner:
    """Runs comprehensive quality drift analysis."""
    
    def __init__(self, exercise_filename: str = "exercise-7.json"):
        # Get the directory where this script is located
        script_dir = Path(__file__).parent
        self.results_dir = script_dir
        # Resolve exercise file path (absolute or under data/samples/)
        if os.path.isabs(exercise_filename):
            self.exercise_data_path = Path(exercise_filename)
        else:
            # Work with sampled exercise files by default
            self.exercise_data_path = script_dir / "data" / "samples" / f"sampled_{exercise_filename}"
    
    def _map_language(self, lang_str: str) -> TextLanguageEnum:
        try:
            return TextLanguageEnum[lang_str.upper()]
        except Exception:
            return TextLanguageEnum.ENGLISH
        
    async def check_and_generate_baseline(self) -> bool:
        """Check if baseline exists, generate if needed."""
        print("🚀 Step 1: Checking baseline feedbacks...")
        print("=" * 60)
        
        try:
            # Load exercise data
            with open(self.exercise_data_path, 'r', encoding='utf-8') as f:
                exercise_data = json.load(f)
            
            # Check if baseline already exists
            if "baseline_info" in exercise_data:
                baseline_info = exercise_data["baseline_info"]
                print(f"✅ Baseline already exists!")
                print(f"🤖 Model: {baseline_info.get('model', 'Unknown')}")
                print(f"📅 Generated: {baseline_info.get('generated_at', 'Unknown')}")
                print(f"📝 Description: {baseline_info.get('description', 'Unknown')}")
                return True
            
            print("🔄 No baseline found. Generating new baseline feedbacks...")
            
            # Generate baseline using GPT-4o
            # Use the baseline_config from conftest.py
            from conftest import baseline_config
            config = baseline_config()
            
            # Create Exercise object
            exercise = Exercise(
                id=exercise_data["id"],
                title=exercise_data["title"],
                type=ExerciseType.text,
                max_points=exercise_data["max_points"],
                bonus_points=exercise_data["bonus_points"],
                grading_instructions=exercise_data["grading_instructions"],
                problem_statement=exercise_data["problem_statement"],
                example_solution=exercise_data["example_solution"],
                grading_criteria=[],
                meta=exercise_data.get("meta", {}),
            )
            
            # Generate timestamp for baseline
            timestamp = datetime.now().isoformat()
            baseline_info = {
                "model": "azure_openai_gpt-4o",
                "approach": "basic",
                "generated_at": timestamp,
                "description": "Baseline feedbacks generated by GPT-4o using basic approach"
            }
            
            # Process all submissions and generate baseline feedbacks
            updated_submissions: List[Dict[str, Any]] = []
            
            for submission_data in exercise_data["submissions"]:
                # Create Submission object
                submission = Submission(
                    id=submission_data["id"],
                    exercise_id=exercise.id,
                    text=submission_data["text"],
                    meta=submission_data.get("meta", {}),
                    language=self._map_language(submission_data.get("language", "ENGLISH")),
                )
                
                print(f"Generating baseline feedbacks for submission {submission.id}...")
                # Generate feedbacks using GPT-4o
                feedbacks = await generate_suggestions(
                    exercise=exercise,
                    submission=submission,
                    config=config,
                    debug=False,
                    is_graded=True,
                    learner_profile=None,
                )
                
                # Convert feedbacks to the format expected in the JSON
                baseline_feedbacks = []
                for i, feedback in enumerate(feedbacks):
                    baseline_feedbacks.append({
                        "id": submission_data["id"] * 100 + i + 1,
                        "description": feedback.description,
                        "title": feedback.title,
                        "index_start": getattr(feedback, 'index_start', None),
                        "index_end": getattr(feedback, 'index_end', None),
                        "credits": feedback.credits,
                        "meta": feedback.meta or {},
                    })
                
                # Create updated submission with baseline feedbacks, preserving original fields
                updated_submission = dict(submission_data)
                updated_submission["feedbacks"] = baseline_feedbacks
                updated_submissions.append(updated_submission)
            
            # Create updated exercise data with baseline info
            updated_exercise_data = {
                "id": exercise_data["id"],
                "course_id": exercise_data["course_id"],
                "title": exercise_data["title"],
                "type": exercise_data["type"],
                "max_points": exercise_data["max_points"],
                "bonus_points": exercise_data["bonus_points"],
                "grading_instructions": exercise_data["grading_instructions"],
                "problem_statement": exercise_data["problem_statement"],
                "example_solution": exercise_data["example_solution"],
                "meta": exercise_data.get("meta", {}),
                "submissions": updated_submissions,
                "baseline_info": baseline_info
            }
            
            # Write updated data back to file
            with open(self.exercise_data_path, 'w', encoding='utf-8') as f:
                json.dump(updated_exercise_data, f, indent=2, ensure_ascii=False)
            
            print(f"✅ Baseline feedbacks generated and saved to {self.exercise_data_path}")
            print(f"📊 Processed {len(updated_submissions)} submissions")
            print(f"🕒 Baseline timestamp: {timestamp}")
            print(f"🤖 Baseline model: {baseline_info['model']} with {baseline_info['approach']} approach")
            
            return True
            
        except Exception as e:
            print(f"❌ Baseline generation failed: {e}")
            return False
    
    async def run_quality_drift_analysis(self) -> Dict[str, Any]:
        """Run quality drift analysis for all models."""
        print("\n🧪 Step 2: Running quality drift analysis...")
        print("=" * 60)
        
        # Load exercise data
        with open(self.exercise_data_path, 'r', encoding='utf-8') as f:
            exercise_data = json.load(f)
        
        # Create Exercise object
        exercise = Exercise(
            id=exercise_data["id"],
            title=exercise_data["title"],
            type=ExerciseType.text,
            max_points=exercise_data["max_points"],
            bonus_points=exercise_data["bonus_points"],
            grading_instructions=exercise_data["grading_instructions"],
            problem_statement=exercise_data["problem_statement"],
            example_solution=exercise_data["example_solution"],
            grading_criteria=[],
            meta=exercise_data.get("meta", {}),
        )
        
        # Initialize analyzer
        analyzer = QualityDriftAnalyzer()
        analyzer.load_baseline_feedbacks(str(self.exercise_data_path))
        
        # Print baseline info
        baseline_info = analyzer.baseline_info
        print(f"\n📋 Baseline Information:")
        print(f"Model: {baseline_info.get('model', 'Unknown')}")
        print(f"Approach: {baseline_info.get('approach', 'Unknown')}")
        print(f"Generated at: {baseline_info.get('generated_at', 'Unknown')}")
        
        # Get all model configurations
        model_configs = get_model_configs()
        
        # Test with all submissions in the sampled exercise file
        test_submissions = exercise_data["submissions"]
        
        all_model_results = {}
        
        for model_info in model_configs:
            model_name = model_info["name"]
            config = model_info["config"]
            
            print(f"\n🧪 Testing {model_name} against baseline...")
            model_results = []
            
            for submission_data in test_submissions:
                submission = Submission(
                    id=submission_data["id"],
                    exercise_id=exercise.id,
                    text=submission_data["text"],
                    meta=submission_data.get("meta", {}),
                    language=self._map_language(submission_data.get("language", "ENGLISH")),
                )
                
                print(f"  Generating feedbacks for submission {submission.id}...")
                
                # Generate test feedbacks
                test_feedbacks = await analyzer.generate_test_feedbacks(
                    config, exercise, submission
                )
                
                # Store test feedbacks
                analyzer.test_feedbacks[submission.id] = test_feedbacks
                
                # Analyze quality drift
                result = analyzer.analyze_quality_drift(submission.id)
                model_results.append(result)
                
                print(f"    BERTScore F1: {result['bertscore']['f1']:.3f}")
                print(f"    Credit drift: {result['credit_drift']['mean_drift']:.2f}")
            
            # Calculate model averages
            avg_bertscore_f1 = np.mean([r['bertscore']['f1'] for r in model_results])
            avg_credit_drift = np.mean([r['credit_drift']['mean_drift'] for r in model_results])
            
            all_model_results[model_name] = {
                "results": model_results,
                "avg_bertscore_f1": avg_bertscore_f1,
                "avg_credit_drift": avg_credit_drift,
                "passed": bool((avg_bertscore_f1 >= MIN_BERTSCORE_F1) and (avg_credit_drift <= MAX_MEAN_CREDIT_DRIFT)),
            }
            
            print(f"  {model_name} - Avg BERTScore F1: {avg_bertscore_f1:.3f}")
            print(f"  {model_name} - Avg credit drift: {avg_credit_drift:.2f}")
        
        return {
            "baseline_info": baseline_info,
            "model_comparison": all_model_results,
            "thresholds": {
                "min_bertscore_f1": MIN_BERTSCORE_F1,
                "max_avg_credit_drift": MAX_MEAN_CREDIT_DRIFT,
            },
            "test_metadata": {
                "exercise_id": exercise.id,
                "submissions_tested": len(test_submissions),
                "models_tested": [m["name"] for m in model_configs]
            }
        }
    
    def generate_comprehensive_report(self, analysis_results: Dict[str, Any]) -> None:
        """Generate/merge a simple analysis report with average metrics per exercise.

        If the report already exists, only the section for the current exercise is updated.
        """
        print("\n📋 Step 3: Generating simple report...")
        print("=" * 60)
        
        # Get current timestamp
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Extract info
        baseline_info = analysis_results.get("baseline_info", {})
        model_comparison = analysis_results.get("model_comparison", {})
        thresholds = analysis_results.get("thresholds", {"min_bertscore_f1": MIN_BERTSCORE_F1, "max_avg_credit_drift": MAX_MEAN_CREDIT_DRIFT})
        test_meta = analysis_results.get("test_metadata", {})
        exercise_id = str(test_meta.get("exercise_id", "unknown"))
        
        # Build per-exercise report block
        per_exercise_report = {
            "timestamp": current_time,
            "exercise_id": test_meta.get("exercise_id"),
            "exercise_file": self.exercise_data_path.name,
            "baseline": {
                "model": baseline_info.get("model", "Unknown"),
                "generated_at": baseline_info.get("generated_at", "Unknown")
            },
            "thresholds": thresholds,
            "model_results": {}
        }
        for model_name, results in model_comparison.items():
            per_exercise_report["model_results"][model_name] = {
                "avg_bertscore_f1": round(results.get("avg_bertscore_f1", 0), 3),
                "avg_credit_drift": round(results.get("avg_credit_drift", 0), 2),
                "passed": bool(results.get("passed", False)),
            }

        # Merge into existing file by exercise id
        report_file = self.results_dir / "quality_drift_report.json"
        merged_report: Dict[str, Any] = {"exercises": {}}
        if report_file.exists():
            try:
                with open(report_file, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
                if isinstance(existing, dict) and isinstance(existing.get("exercises"), dict):
                    merged_report = existing
                else:
                    # Preserve legacy single-exercise structure under a "legacy" key
                    merged_report = {"exercises": {"legacy": existing}}
            except Exception:
                merged_report = {"exercises": {}}
        
        merged_report.setdefault("exercises", {})[exercise_id] = per_exercise_report
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(merged_report, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Simple report saved/updated for exercise {exercise_id} → {report_file}")
        
        # Print summary
        self.print_analysis_summary(analysis_results)
    
    def print_analysis_summary(self, analysis_results: Dict[str, Any]) -> None:
        """Print a summary of the analysis results."""
        print("\n📊 Quality Drift Analysis Summary")
        print("=" * 60)
        
        baseline_info = analysis_results.get("baseline_info", {})
        model_comparison = analysis_results.get("model_comparison", {})
        thresholds = analysis_results.get("thresholds", {"min_bertscore_f1": MIN_BERTSCORE_F1, "max_avg_credit_drift": MAX_MEAN_CREDIT_DRIFT})

        total_models = len(model_comparison)
        passed_models = sum(1 for _, res in model_comparison.items() if res.get("passed"))
        print(f"Tests: {passed_models}/{total_models} passed (min F1 >= {thresholds['min_bertscore_f1']}, max credit drift <= {thresholds['max_avg_credit_drift']})")
        
        print(f"\n🤖 Model Comparison Results:")
        print(f"Baseline: {baseline_info.get('model', 'Unknown')}")
        print(f"Generated: {baseline_info.get('generated_at', 'Unknown')}")
        print("\nModel Results:")
        for model_name, results in model_comparison.items():
            f1_score = results.get("avg_bertscore_f1", 0)
            credit_drift = results.get("avg_credit_drift", 0)
            status = "✅" if results.get("passed") else "❌"
            print(f"  {model_name}: {status} BERTScore F1={f1_score:.3f}, Credit Drift={credit_drift:.2f}")
        
        print(f"\n📅 Analysis completed at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("✅ Quality drift analysis pipeline completed!")


async def main():
    """Main execution function."""
    print("🎯 Quality Drift Analysis Pipeline")
    print("=" * 60)
    print("This pipeline will:")
    print("1. Check/generate baseline feedbacks using GPT-4o for ALL sampled exercises")
    print("2. Run quality drift analysis tests for ALL models on ALL exercises")
    print("3. Generate comprehensive reports")
    print("=" * 60)
    
    # Get the directory where this script is located
    script_dir = Path(__file__).parent
    samples_dir = script_dir / "data" / "samples"
    
    # Find all sampled exercise files
    sampled_files = list(samples_dir.glob("sampled_exercise-*.json"))
    
    if not sampled_files:
        print("❌ No sampled exercise files found in data/samples/")
        print("Please run the sampling script first to create sampled exercise files.")
        sys.exit(1)
    
    print(f"📁 Found {len(sampled_files)} sampled exercise files:")
    for file in sampled_files:
        print(f"  - {file.name}")
    
    # Process each sampled exercise file
    for sampled_file in sampled_files:
        print(f"\n{'='*80}")
        print(f"🔍 Processing: {sampled_file.name}")
        print(f"{'='*80}")
        
        # Extract exercise filename from sampled filename
        exercise_filename = sampled_file.name.replace("sampled_", "")
        
        # Create runner for this exercise
        runner = QualityDriftAnalysisRunner(exercise_filename=exercise_filename)
        
        # Step 1: Check and generate baseline if needed
        baseline_success = await runner.check_and_generate_baseline()
        if not baseline_success:
            print(f"❌ Baseline check/generation failed for {exercise_filename}. Skipping to next exercise.")
            continue
        
        # Step 2: Run quality drift analysis
        analysis_results = await runner.run_quality_drift_analysis()
        
        # Step 3: Generate comprehensive report
        runner.generate_comprehensive_report(analysis_results)
        
        print(f"✅ Completed processing {exercise_filename}")
    
    print(f"\n🎉 Quality drift analysis pipeline completed for {len(sampled_files)} exercises!")


if __name__ == "__main__":
    asyncio.run(main())
