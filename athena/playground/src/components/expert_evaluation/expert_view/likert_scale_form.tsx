import React from 'react';
import SingleChoiceLikertScale from "@/components/expert_evaluation/expert_view/likert_scale";
import TextSubmissionDetail from "@/components/details/submission_detail/text";
import type { TextSubmission } from "@/model/submission";
import { CategorizedFeedback } from "@/model/feedback";
import { Exercise } from "@/model/exercise";
import { Metric } from "@/model/metric";

interface LikertScaleFormProps {
    submission: TextSubmission;
    exercise: Exercise;
    feedback: CategorizedFeedback;
    metrics: Metric[];
    selectedValues: { // Selected values for each exercise, submission, and feedback type
        [exerciseId: string]: {
            [submissionId: string]: {
                [feedbackType: string]: {
                    [metricId: string]: number; // The Likert scale value for a metric
                };
            };
        };
    };
    onLikertValueChange: (feedbackType: string, metricId: string, value: number) => void;
    isMarkMissingValue: boolean
}


export default function LikertScaleForm(likertScaleFormProps: LikertScaleFormProps) {
    const {
        submission,
        exercise,
        feedback,
        metrics,
        selectedValues,
        onLikertValueChange,
        isMarkMissingValue,
    } = likertScaleFormProps;

    if (!exercise || !submission) {
        return <div>Loading...</div>;
    }

    return (
        <div className="overflow-x-scroll">
            <div className="flex space-x-6">
                {Object.entries(feedback).map(([feedbackType, feedbackList]) => (
                    <div key={feedbackType} className="flex-1 min-w-[480px] flex flex-col">
                        {/* Render TextSubmissionDetail */}
                        <div className="flex-grow flex flex-col mb-4">
                            <TextSubmissionDetail
                                identifier={`id-${submission.id}-${feedbackType}`}
                                key={submission.id}
                                submission={submission}
                                feedbacks={feedbackList}
                                onFeedbacksChange={undefined}
                                hideFeedbackDetails={true}
                            />
                        </div>

                        {/* Render SingleChoiceLikertScale components */}
                        <div className="flex flex-col mt-auto mb-4">
                            {metrics.map((metric) => {
                                const selectedValue =
                                    selectedValues?.[exercise.id]?.[submission.id]?.[feedbackType]?.[metric.id] ?? null;
                                const isHighlighted = isMarkMissingValue && (selectedValue === null);

                                return (
                                    <div key={`${feedbackType}-${metric.id}`} className="mb-2">
                                        <SingleChoiceLikertScale
                                            title={metric.title}
                                            summary={metric.summary}
                                            description={metric.description}
                                            passedValue={selectedValue}
                                            onLikertChange={(value: number) =>
                                                onLikertValueChange(feedbackType, metric.id, value)
                                            }
                                            isHighlighted={isHighlighted}
                                        />
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};
