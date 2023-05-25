import path from "path";
import fs from "fs";

import {Exercise} from "@/model/exercise";
import {Submission} from "@/model/submission";
import Feedback from "@/model/feedback";


function getExampleExerciseJSON(exerciseId: number): any {
    // find in cwd/examples/submissions/<exerciseId>.json
    const submissionsPath = path.join(process.cwd(), 'examples', `exercise-${exerciseId}.json`);
    if (fs.existsSync(submissionsPath)) {
        return JSON.parse(fs.readFileSync(submissionsPath, 'utf8'));
    }
    throw new Error(`No example submissions found for exercise ${exerciseId}`);
}

function getAllExampleExerciseJSON(): any[] {
    // find in cwd/examples/submissions/*.json
    const submissionsPath = path.join(process.cwd(), 'examples');
    const exerciseIds = fs.readdirSync(submissionsPath)
        .filter((fileName) => fileName.endsWith('.json'))
        .map((fileName) => {
            // filename looks like `exercise-<exerciseId>.json`
            return parseInt(fileName.split('.')[0].split('-')[1]);
        });
    return exerciseIds.map(getExampleExerciseJSON);
}


function jsonToExercise(json: any): Exercise {
    const exercise = json as Exercise;
    // drop submissions from response to have a real Exercise
    // @ts-ignore
    delete exercise['submissions'];
    return exercise;
}

function jsonToSubmissions(json: any): Submission[] {
    return json.submissions.map((submissionJson: any) => {
        const submission = submissionJson as Submission;
        // exercise_id is not provided in the json for convenience, so we add it here
        submission.exercise_id = json.id;
        // drop feedbacks from response to have a real Submission
        // @ts-ignore
        delete submission['feedbacks'];
        return submission;
    });
}

function jsonToFeedbacks(json: any): Feedback[] {
    let feedbacks: Feedback[] = [];

    json.submissions.forEach((submissionJson: any) => {
        if (submissionJson.feedbacks) {
            const additionalFeedbacks = submissionJson.feedbacks.map((feedbackJson: any) => {
                const feedback = feedbackJson as Feedback;
                // exercise_id is not provided in the json for convenience, so we add it here
                feedback.exercise_id = json.id;
                // submission_id is not provided in the json for convenience, so we add it here
                feedback.submission_id = submissionJson.id;
                return feedback;
            });
            feedbacks = [...feedbacks, ...additionalFeedbacks];
        }
    });

    return feedbacks;
}


export function getExampleExercises(): Exercise[] {
    return getAllExampleExerciseJSON().map(jsonToExercise);
}

export function getExampleSubmissions(exerciseId?: number): Submission[] {
    if (exerciseId !== undefined) {
        return jsonToSubmissions(getExampleExerciseJSON(exerciseId));
    }
    return getAllExampleExerciseJSON().flatMap(jsonToSubmissions);
}

export function getExampleFeedbacks(exerciseId?: number): Feedback[] {
    if (exerciseId !== undefined) {
        return jsonToFeedbacks(getExampleExerciseJSON(exerciseId));
    }
    return getAllExampleExerciseJSON().flatMap(jsonToFeedbacks);
}