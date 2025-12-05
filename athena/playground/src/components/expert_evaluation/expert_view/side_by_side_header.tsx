import React, { useState } from 'react';
import Popup from "@/components/expert_evaluation/expert_view/popup";
import { Metric } from "@/model/metric";
import rehypeRaw from "rehype-raw";
import ReactMarkdown from "react-markdown";
import ExerciseDetailPopup from "@/components/expert_evaluation/expert_view/exercise_detail_popup";
import TutorialPopup from "@/components/expert_evaluation/expert_view/tutorial_popup";
import { SecondaryButton, NextButton, PrimaryButton } from "@/components/expert_evaluation/expert_evaluation_buttons";

type SideBySideHeaderProps = {
    exercise: any;
    globalSubmissionIndex: number;
    totalSubmissions: number;
    metrics: Metric[];
    onNext: () => void;
    onPrevious: () => void;
    onContinueLater: () => void;
}

export default function SideBySideHeader(sideBySideHeaderProps: SideBySideHeaderProps) {
    const {
        exercise,
        globalSubmissionIndex,
        totalSubmissions,
        metrics,
        onNext,
        onPrevious,
        onContinueLater,
    } = sideBySideHeaderProps;
    const [isExerciseDetailOpen, setIsExerciseDetailOpen] = useState<boolean>(false);
    const [isMetricDetailOpen, setIsMetricDetailOpen] = useState<boolean>(false);
    const [isEvaluationTutorialOpen, setIsEvaluationTutorialOpen] = useState<boolean>(false);

    const openExerciseDetail = () => setIsExerciseDetailOpen(true);
    const closeExerciseDetail = () => setIsExerciseDetailOpen(false);
    const openMetricDetail = () => setIsMetricDetailOpen(true);
    const closeMetricDetail = () => setIsMetricDetailOpen(false);
    const openEvaluationTutorial = () => setIsEvaluationTutorialOpen(true);
    const closeEvaluationTutorial = () => setIsEvaluationTutorialOpen(false);

    if (!exercise) {
        return <div>Loading...</div>;
    }

    return (
        <div className="mb-4 sticky top-0 z-10 bg-white"> {/* Sticky header */}
            {/* Subtitle and Details Buttons Section */}
            <div className="flex flex-col md:flex-row justify-between items-start md:items-end gap-4 mb-4">

                {/* Align heading to the top */}
                <div className="flex flex-col gap-2 w-full md:w-auto self-start">
                    <h1 className="text-xl font-semibold text-gray-900">
                        Evaluation: {exercise.title}
                    </h1>

                    {/* Details Buttons */}
                    <div className="flex flex-col md:flex-row gap-2 w-full">
                        <SecondaryButton text={'📄 Exercise Details'} onClick={openExerciseDetail} />
                        <ExerciseDetailPopup
                            exercise={exercise}
                            isOpen={isExerciseDetailOpen}
                            onClose={closeExerciseDetail} />

                        <SecondaryButton text={'📊 Metric Details'} onClick={openMetricDetail} />
                        <Popup isOpen={isMetricDetailOpen} onClose={closeMetricDetail} title="Metric Details">
                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                                {metrics.map((metric, index) => (
                                    <div key={index} className="border border-gray-300 rounded-md p-4">
                                        <h2 className="font-semibold mb-4">{metric.title}</h2>
                                        <div className="prose-sm">
                                            <ReactMarkdown rehypePlugins={[rehypeRaw]}>
                                                {metric.description}
                                            </ReactMarkdown>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </Popup>

                        <SecondaryButton text={'📚 Evaluation Tutorial'} onClick={openEvaluationTutorial} />
                        <TutorialPopup isOpen={isEvaluationTutorialOpen} onClose={closeEvaluationTutorial} />
                    </div>
                </div>

                {/* Align buttons to the end */}
                <div className="flex flex-col items-end gap-2 mt-4 md:mt-0 w-full md:w-[250px] self-end">
                    <SecondaryButton text={'😴 Continue Later'} onClick={onContinueLater} className={'w-full'} />

                    {/* Wrapping buttons to match the width */}
                    <div className="flex gap-2 w-full md:w-[250px]">
                        <PrimaryButton text={'⬅️ Previous'} onClick={onPrevious} isDisabled={globalSubmissionIndex === 0} className={'w-full'} />
                        <NextButton onClick={onNext} isFinish={globalSubmissionIndex === totalSubmissions - 1} />
                    </div>
                </div>
            </div>

            {/* Progress Bar */}
            <div className="relative w-full bg-gray-300 h-2 rounded">
                <div
                    className="bg-blue-500 h-2 rounded"
                    style={{ width: `${(globalSubmissionIndex + 1) / totalSubmissions * 100}%` }}
                />
            </div>
            <span className="text-sm text-gray-700">
                {globalSubmissionIndex + 1} / {totalSubmissions}
            </span>
        </div>
    );
}
