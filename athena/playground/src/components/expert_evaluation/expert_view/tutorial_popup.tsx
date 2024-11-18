import React, { useState } from 'react';
import Popup from "@/components/expert_evaluation/expert_view/popup";
import exerciseDetails from "@/assets/evaluation_tutorial/exercise_details.gif";
import readSubmission from "@/assets/evaluation_tutorial/read_submission.gif";
import evaluateMetrics from "@/assets/evaluation_tutorial/evaluate_metrics.gif";
import metricsExplanation from "@/assets/evaluation_tutorial/metrics-explanation.gif";
import viewNext from "@/assets/evaluation_tutorial/view-next.gif";
import continueLater from "@/assets/evaluation_tutorial/continue_later.gif";
import {
    InfoIconButton,
    NextButton,
    PrimaryButton,
    SecondaryButton
} from "@/components/expert_evaluation/expert_evaluation_buttons";
import { Exercise } from "@/model/exercise";
import ExerciseDetail from "@/components/details/exercise_detail";

const baseTutorialSteps = [
    {
        image: exerciseDetails.src,
        description: (
            <>
                1. Read the
                <SecondaryButton text={'📄 Exercise Details'} isInline={true} className="mx-1" />
            </>
        ),
    },
    {
        image: readSubmission.src,
        description: "2. Read the Submission and the corresponding feedback"
    },
    {
        image: evaluateMetrics.src,
        description: "3. Evaluate the feedback based on the metrics"
    },
    {
        image: metricsExplanation.src,
        description: (
            <>
                4. If unsure what a metric means, press the
                <InfoIconButton className="mx-1" />
                or look at the
                <SecondaryButton text={'📊 Metric Details'} isInline={true} className="mx-1" />
            </>
        ),
    },
    {
        image: viewNext.src,
        description: (
            <>
                5. After evaluating all metrics for all feedbacks, click on the
                <NextButton isInline={true} className="mx-1" /> button to view the next submission.
            </>),
    },
    {
        image: continueLater.src,
        description: (
            <>
                6. When you are ready to take a break, click on the
                <SecondaryButton text={'😴 Continue Later'} isInline={true} className="mx-1" />
            </>
        ),
    },
];

interface TutorialPopupProps {
    isOpen: boolean;
    onClose: () => void;
    disableCloseOnOutsideClick?: boolean;
    exercise?: Exercise;
}

export default function TutorialPopup(tutorialPopupProps: TutorialPopupProps) {
    const { isOpen, onClose, disableCloseOnOutsideClick, exercise } = tutorialPopupProps;
    const [currentStep, setCurrentStep] = useState(0);

    // If the tutorial was opened in welcome window, add a last step involving the first exercise
    const tutorialSteps = exercise
        ? [
            ...baseTutorialSteps,
            {
                image: "",
                description: (
                    <>
                        <div className="text-left">
                            Now you are ready to start the evaluation! Read the description of the first exercise

                            <ExerciseDetail exercise={exercise} hideDisclosure={true} openedInitially={true} />
                        </div>
                    </>),
            },
        ]
        : baseTutorialSteps;

    const handleNext = () => {
        if (currentStep < tutorialSteps.length - 1) {
            setCurrentStep(currentStep + 1);
        }
    };

    const handlePrevious = () => {
        if (currentStep > 0) {
            setCurrentStep(currentStep - 1);
        }
    };

    const { image, description } = tutorialSteps[currentStep];

    const isLastStep = currentStep === tutorialSteps.length - 1;
    return (
        <Popup isOpen={isOpen} onClose={onClose} title="Evaluation Tutorial"
            disableCloseOnOutsideClick={disableCloseOnOutsideClick}>
            <div className="text-center">
                {/* Display the current GIF */}
                {image && <img src={image} alt={`Tutorial Step ${currentStep + 1}`} className="w-full h-auto mb-4" />}

                {/* Render the description directly, which may include text and button */}
                <div className={"text-lg mb-4"}>
                    {description}
                </div>

                {/* Navigation buttons */}
                <div className="flex justify-between mt-4">
                    <SecondaryButton
                        text="Previous"
                        onClick={handlePrevious}
                        isDisabled={currentStep === 0}
                    />
                    <span className="text-lg">{`${currentStep + 1} / ${tutorialSteps.length}`}</span>
                    <PrimaryButton
                        onClick={isLastStep ? onClose : handleNext}
                        text={isLastStep ? 'Start Evaluation' : 'Next ➡️'}
                    />
                </div>
            </div>
        </Popup>
    );
};
