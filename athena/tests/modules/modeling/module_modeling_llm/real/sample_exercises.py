#!/usr/bin/env python3
"""
Script to sample modeling exercises by selecting one submission from each score range.
This replicates the sampling strategy used in exercise files but for modeling exercises.
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

def get_score_range(score: float) -> str:
    """Convert score to score range string."""
    if score == 0:
        return "0"
    elif score == 100:
        return "100"
    else:
        # Round down to nearest 10 and create range
        lower = (int(score) // 10) * 10
        upper = lower + 9
        return f"{lower}-{upper}"

def sample_exercise(exercise_file: Path) -> Optional[Dict]:
    """
    Sample a modeling exercise file by selecting one submission from each score range.
    
    Returns:
        Dict with sampled submissions or None if file can't be processed
    """
    try:
        with open(exercise_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Get all submissions (modeling exercises don't have language field)
        all_submissions = data.get('submissions', [])
        
        if not all_submissions:
            print(f"No submissions found in {exercise_file.name}")
            return None
        
        # Group submissions by score range
        score_groups = {}
        for submission in all_submissions:
            score = submission.get('score', 0)
            score_range = get_score_range(score)
            
            if score_range not in score_groups:
                score_groups[score_range] = []
            score_groups[score_range].append(submission)
        
        # Select one submission from each score range
        sampled_submissions = []
        target_ranges = [
            "0", "0-9", "10-19", "20-29", "30-39", "40-49", 
            "50-59", "60-69", "70-79", "80-89", "90-99", "100"
        ]
        
        for target_range in target_ranges:
            if target_range in score_groups:
                # Take the first submission from this score range
                sampled_submissions.append(score_groups[target_range][0])
                print(f"  {target_range}: score {score_groups[target_range][0]['score']}")
            else:
                print(f"  {target_range}: No submissions found")
        
        # Create new exercise data with sampled submissions
        sampled_data = data.copy()
        sampled_data['submissions'] = sampled_submissions
        
        return sampled_data
        
    except Exception as e:
        print(f"Error processing {exercise_file.name}: {e}")
        return None

def main():
    """Main function to process all exercise files."""
    # Get the directory where this script is located
    script_dir = Path(__file__).parent
    
    # Define input and output directories relative to script location
    exercises_dir = script_dir / "data" / "exercises"
    samples_dir = script_dir / "data" / "samples"
    
    if not exercises_dir.exists():
        print(f"Exercises directory {exercises_dir} not found!")
        print(f"Current working directory: {os.getcwd()}")
        print(f"Script directory: {script_dir}")
        print(f"Looking for exercises in: {exercises_dir.absolute()}")
        return
    
    # Create samples directory if it doesn't exist
    samples_dir.mkdir(exist_ok=True)
    
    # Get all exercise JSON files from exercises directory
    exercise_files = list(exercises_dir.glob("exercise-*.json"))
    exercise_files.sort()
    
    print(f"Found {len(exercise_files)} exercise files in {exercises_dir}")
    
    # Process each exercise file
    for exercise_file in exercise_files:
        print(f"\nProcessing {exercise_file.name}...")
        
        # Sample the exercise
        sampled_data = sample_exercise(exercise_file)
        
        if sampled_data:
            # Create output filename in samples directory
            output_file = samples_dir / f"sampled_{exercise_file.name}"
            
            # Save sampled data
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(sampled_data, f, indent=2, ensure_ascii=False)
            
            print(f"  Saved sampled exercise to {output_file.name}")
            print(f"  Sampled submissions: {len(sampled_data['submissions'])}")
        else:
            print(f"  Failed to process {exercise_file.name}")
    
    print("\nSampling complete!")

if __name__ == "__main__":
    main()
