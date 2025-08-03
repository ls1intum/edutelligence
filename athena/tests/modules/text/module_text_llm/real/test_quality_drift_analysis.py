import json
import pytest
from typing import List, Dict, Any, Tuple
from pathlib import Path

from athena.text import Exercise, Submission, Feedback
from athena.schemas.exercise_type import ExerciseType
from athena.schemas.text_submission import TextLanguageEnum
from module_text_llm.basic_approach.generate_suggestions import generate_suggestions as basic_generate_suggestions
from module_text_llm.chain_of_thought_approach.generate_suggestions import generate_suggestions as chain_of_thought_generate_suggestions
import random
# Import BERTScore for semantic similarity
try:
    from bert_score import score
    BERTSCORE_AVAILABLE = True
except ImportError:
    BERTSCORE_AVAILABLE = False
    print("Warning: BERTScore not available. Install with: pip install bert-score")


class QualityDriftAnalyzer:
    """Helper class to analyze quality drift between different approaches."""
    
    def __init__(self, data_dir: str = None):
        if data_dir is None:
            self.data_dir = Path(__file__).parent.parent.parent.parent.parent.parent / "playground" / "data" / "example"
        else:
            self.data_dir = Path(data_dir)
    
    def load_exercise_data(self, exercise_id: int) -> Tuple[Exercise, List[Submission]]:
        """Load exercise and its submissions."""
        exercise_file = self.data_dir / f"exercise-{exercise_id}.json"
        if not exercise_file.exists():
            raise FileNotFoundError(f"Exercise file not found: {exercise_file}")
        
        with open(exercise_file, 'r', encoding='utf-8') as f:
            exercise_data = json.load(f)
        
        # Convert to Athena Exercise
        exercise = Exercise(
            id=exercise_data["id"],
            title=exercise_data["title"],
            type=ExerciseType(exercise_data["type"]),
            max_points=exercise_data["max_points"],
            bonus_points=exercise_data.get("bonus_points", 0),
            grading_instructions=exercise_data.get("grading_instructions", ""),
            problem_statement=exercise_data.get("problem_statement", ""),
            example_solution=exercise_data.get("example_solution", ""),
            grading_criteria=[],
            meta=exercise_data.get("meta", {}),
        )
        
        # Convert submissions
        submissions = []
        for submission_data in exercise_data["submissions"]:
            submission = Submission(
                id=submission_data["id"],
                exercise_id=exercise.id,
                text=submission_data.get("text", ""),
                meta=submission_data.get("meta", {}),
                language=TextLanguageEnum.ENGLISH,
            )
            submissions.append(submission)
        
        return exercise, submissions
    
    def calculate_drift_metrics(self, baseline_feedbacks: List[Feedback], test_feedbacks: List[Feedback]) -> Dict[str, Any]:
        """Calculate drift metrics between baseline and test approaches."""
        
        # Basic statistics
        baseline_count = len(baseline_feedbacks)
        test_count = len(test_feedbacks)
        
        # Calculate overlap in feedback content (simple text similarity)
        baseline_descriptions = [f.description.lower() for f in baseline_feedbacks]
        test_descriptions = [f.description.lower() for f in test_feedbacks]
        
        # Simple keyword matching (Jaccard similarity)
        baseline_keywords = set()
        for desc in baseline_descriptions:
            baseline_keywords.update(desc.split())
        
        test_keywords = set()
        for desc in test_descriptions:
            test_keywords.update(desc.split())
        
        keyword_overlap = len(baseline_keywords.intersection(test_keywords))
        keyword_union = len(baseline_keywords.union(test_keywords))
        keyword_similarity = keyword_overlap / keyword_union if keyword_union > 0 else 0
        
        # BERTScore semantic similarity
        bert_score_similarity = 0.0
        if BERTSCORE_AVAILABLE and baseline_descriptions and test_descriptions:
            try:
                # Combine all baseline feedback into one text
                baseline_text = " ".join(baseline_descriptions)
                # Combine all test feedback into one text
                test_text = " ".join(test_descriptions)
                
                # Calculate BERTScore
                P, R, F1 = score([test_text], [baseline_text], lang='en', verbose=False)
                bert_score_similarity = F1.mean().item()  # Use F1 score as similarity metric
            except Exception as e:
                print(f"BERTScore calculation failed: {e}")
                bert_score_similarity = 0.0
        
        
        return {
            "baseline_feedback_count": baseline_count,
            "test_feedback_count": test_count,
            "keyword_similarity": keyword_similarity,
            "bert_score_similarity": bert_score_similarity,
        }


@pytest.fixture
def drift_analyzer():
    """Fixture to provide a quality drift analyzer."""
    return QualityDriftAnalyzer()



@pytest.mark.asyncio
async def test_quality_drift_comprehensive_analysis(real_config, chain_of_thought_config, drift_analyzer):
    """Comprehensive quality drift analysis with detailed feedback comparison and quality threshold enforcement."""
    
    # Load exercise 7 data (with structured grading criteria)
    exercise, submissions = drift_analyzer.load_exercise_data(7)
    
    print(f"\n=== Comprehensive Quality Drift Analysis: Basic vs Chain of Thought ===")
    print(f"Exercise: {exercise.title}")
    print(f"Total submissions: {len(submissions)}")
    
    # Test with a subset of submissions for performance
    test_submissions = random.sample(submissions, 5)  # 5 randomly selected submissions
    
    # Generate all feedbacks first (one call per approach per submission)
    print(f"\nGenerating feedbacks for {len(test_submissions)} submissions...")
    
    baseline_results = {}
    test_results = {}
    
    for submission in test_submissions:
        print(f"  Generating feedback for submission {submission.id}...")
        
        # Generate feedback using baseline approach (basic)
        baseline_feedbacks = await basic_generate_suggestions(
            exercise=exercise,
            submission=submission,
            config=real_config,
            debug=False,
            is_graded=True,
        )
        baseline_results[submission.id] = baseline_feedbacks
        
        # Generate feedback using test approach (chain of thought)
        test_feedbacks = await chain_of_thought_generate_suggestions(
            exercise=exercise,
            submission=submission,
            config=chain_of_thought_config,
            debug=False,
            is_graded=True,
        )
        test_results[submission.id] = test_feedbacks
    
    # Now analyze the results with detailed feedback comparison
    print(f"\nAnalyzing quality drift with detailed feedback comparison...")
    all_metrics = []
    
    for submission in test_submissions:
        baseline_feedbacks = baseline_results[submission.id]
        test_feedbacks = test_results[submission.id]
        
        print(f"\n--- Submission {submission.id} Analysis ---")
        print(f"Text: {submission.text[:200]}...")
        
        # Show what each approach generated
        print(f"\nBaseline approach feedbacks ({len(baseline_feedbacks)}):")
        for i, feedback in enumerate(baseline_feedbacks, 1):
            print(f"  {i}. Title: {feedback.title}")
            print(f"     Description: {feedback.description[:400]}...")
        
        print(f"\nChain of Thought approach feedbacks ({len(test_feedbacks)}):")
        for i, feedback in enumerate(test_feedbacks, 1):
            print(f"  {i}. Title: {feedback.title}")
            print(f"     Description: {feedback.description[:400]}...")
        
        # Calculate drift metrics
        metrics = drift_analyzer.calculate_drift_metrics(baseline_feedbacks, test_feedbacks)
        metrics["submission_id"] = submission.id
        metrics["submission_text"] = submission.text[:50] + "..." if len(submission.text) > 50 else submission.text
        
        all_metrics.append(metrics)
        
        print(f"\nDrift Metrics:")
        print(f"  Keyword similarity: {metrics['keyword_similarity']:.3f}")
        print(f"  BERTScore: {metrics['bert_score_similarity']:.3f}")
        print("-" * 100)
    
    # Overall statistics and quality threshold enforcement
    if all_metrics:
        avg_keyword_similarity = sum(m["keyword_similarity"] for m in all_metrics) / len(all_metrics)
        avg_bert_score = sum(m["bert_score_similarity"] for m in all_metrics) / len(all_metrics)
        
        print(f"\n=== Overall Drift Analysis ===")
        print(f"Average keyword similarity: {avg_keyword_similarity:.3f}")
        print(f"Average BERTScore: {avg_bert_score:.3f}")
        
        # Quality thresholds for CI/CD pipeline
        MIN_KEYWORD_SIMILARITY = 0.2  # At least 20% keyword overlap
        MIN_BERT_SCORE = 0.8  # At least 80% BERTScore similarity
        
        # Assertions for quality drift detection
        assert avg_keyword_similarity >= MIN_KEYWORD_SIMILARITY, \
            f"Keyword similarity ({avg_keyword_similarity:.3f}) below threshold ({MIN_KEYWORD_SIMILARITY})"
        
        if BERTSCORE_AVAILABLE:
            assert avg_bert_score >= MIN_BERT_SCORE, \
                f"BERTScore similarity ({avg_bert_score:.3f}) below threshold ({MIN_BERT_SCORE})"
        
        print(f"✅ Quality drift analysis passed all thresholds!")
        print(f"✅ Basic approach (baseline) and Chain of Thought approach show acceptable similarity")
        
        assert len(all_metrics) > 0, "Should have evaluated at least one submission"


@pytest.mark.asyncio
async def test_quality_drift_gpt4o_vs_gpt35(real_config, gpt35_config, drift_analyzer):
    """Quality drift analysis comparing GPT-4o vs GPT-3.5-turbo using basic approach."""
    
    # Load exercise 8 data (with structured grading criteria)
    exercise, submissions = drift_analyzer.load_exercise_data(8)
    
    print(f"\n=== Quality Drift Analysis: GPT-4o vs GPT-3.5-turbo (Basic Approach) ===")
    print(f"Exercise: {exercise.title}")
    print(f"Total submissions: {len(submissions)}")
    
    # Test with a subset of submissions for performance
    test_submissions = random.sample(submissions, 5)  # 5 randomly selected submissions
    
    # Generate all feedbacks first (one call per model per submission)
    print(f"\nGenerating feedbacks for {len(test_submissions)} submissions...")
    
    gpt4o_results = {}
    gpt35_results = {}
    
    for submission in test_submissions:
        print(f"  Generating feedback for submission {submission.id}...")
        
        # Generate feedback using GPT-4o (baseline)
        gpt4o_feedbacks = await basic_generate_suggestions(
            exercise=exercise,
            submission=submission,
            config=real_config,  # Uses GPT-4o
            debug=False,
            is_graded=True,
        )
        gpt4o_results[submission.id] = gpt4o_feedbacks
        
        # Generate feedback using GPT-3.5-turbo (test)
        gpt35_feedbacks = await basic_generate_suggestions(
            exercise=exercise,
            submission=submission,
            config=gpt35_config,  # Uses GPT-3.5-turbo
            debug=False,
            is_graded=True,
        )
        gpt35_results[submission.id] = gpt35_feedbacks
    
    # Now analyze the results with detailed feedback comparison
    print(f"\nAnalyzing quality drift between GPT-4o and GPT-3.5-turbo...")
    all_metrics = []
    
    for submission in test_submissions:
        gpt4o_feedbacks = gpt4o_results[submission.id]
        gpt35_feedbacks = gpt35_results[submission.id]
        
        print(f"\n--- Submission {submission.id} Analysis ---")
        print(f"Text: {submission.text[:200]}...")
        
        # Show what each model generated
        print(f"\nGPT-4o feedbacks ({len(gpt4o_feedbacks)}):")
        for i, feedback in enumerate(gpt4o_feedbacks, 1):
            print(f"  {i}. Title: {feedback.title}")
            print(f"     Description: {feedback.description[:400]}...")
        
        print(f"\nGPT-3.5-turbo feedbacks ({len(gpt35_feedbacks)}):")
        for i, feedback in enumerate(gpt35_feedbacks, 1):
            print(f"  {i}. Title: {feedback.title}")
            print(f"     Description: {feedback.description[:400]}...")
        
        # Calculate drift metrics
        metrics = drift_analyzer.calculate_drift_metrics(gpt4o_feedbacks, gpt35_feedbacks)
        metrics["submission_id"] = submission.id
        metrics["submission_text"] = submission.text[:50] + "..." if len(submission.text) > 50 else submission.text
        
        all_metrics.append(metrics)
        
        print(f"\nDrift Metrics:")
        print(f"  Keyword similarity: {metrics['keyword_similarity']:.3f}")
        print(f"  BERTScore: {metrics['bert_score_similarity']:.3f}")
        print("-" * 100)
    
    # Overall statistics and quality threshold enforcement
    if all_metrics:
        avg_keyword_similarity = sum(m["keyword_similarity"] for m in all_metrics) / len(all_metrics)
        avg_bert_score = sum(m["bert_score_similarity"] for m in all_metrics) / len(all_metrics)
        
        print(f"\n=== Overall Model Comparison Analysis ===")
        print(f"Average keyword similarity: {avg_keyword_similarity:.3f}")
        print(f"Average BERTScore: {avg_bert_score:.3f}")
        
        # Quality thresholds for model comparison
        MIN_KEYWORD_SIMILARITY = 0.10  
        MIN_BERT_SCORE = 0.75
        
        # Assertions for quality drift detection
        assert avg_keyword_similarity >= MIN_KEYWORD_SIMILARITY, \
            f"Keyword similarity ({avg_keyword_similarity:.3f}) below threshold ({MIN_KEYWORD_SIMILARITY})"
        
        if BERTSCORE_AVAILABLE:
            assert avg_bert_score >= MIN_BERT_SCORE, \
                f"BERTScore similarity ({avg_bert_score:.3f}) below threshold ({MIN_BERT_SCORE})"
        
        print(f"✅ Model comparison analysis passed all thresholds!")
        print(f"✅ GPT-4o and GPT-3.5-turbo show acceptable similarity for basic approach")
        
        assert len(all_metrics) > 0, "Should have evaluated at least one submission"


 