import React, { useState } from 'react';
import ExerciseDetailPopup from "@/components/expert_evaluation/expert_view/exercise_detail_popup";
import { Exercise } from "@/model/exercise";
import { SecondaryButton } from "@/components/expert_evaluation/expert_evaluation_buttons";
import background_image from "@/assets/evaluation_backgrounds/exercise.jpeg";

interface ExerciseScreenProps {
  onCloseExerciseDetail: () => void;
  onOpenContinueLater: () => void;
  exercise: Exercise;
  currentExerciseIndex: number;
  totalExercises: number;
}

export default function ExerciseScreen(exerciseScreenProps: ExerciseScreenProps) {
  const {
    onCloseExerciseDetail,
    onOpenContinueLater,
    exercise,
    currentExerciseIndex,
    totalExercises,
  } = exerciseScreenProps;
  const [isExerciseDetailOpen, setExerciseDetailOpen] = useState(false);

  const closeExerciseDetail = () => {
    setExerciseDetailOpen(false);
    onCloseExerciseDetail();
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50"
      style={{
        backgroundImage: `url(${background_image.src})`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
      }}
    >
      <div className="bg-white p-8 rounded-lg shadow-lg max-w-lg w-full text-center">
        <h1 className="text-4xl font-bold mb-4">You have
          evaluated {currentExerciseIndex}/{totalExercises} exercises!</h1>
        <p className="text-lg mb-6">
          Great job! Feel free to take a break and
          continue later. Your progress has been saved.
        </p>
        <p className="text-lg mb-6">
          When you are ready, continue with the next exercise: {exercise.title}.
        </p>
        <div className="flex justify-center mt-4">
          <SecondaryButton
            onClick={onOpenContinueLater}
            text="😴 Continue Later"
            className="px-6 py-3"
          />

          <SecondaryButton
            onClick={() => setExerciseDetailOpen(true)}
            text="📄 Exercise Details"
            className="ml-4 px-6 py-3"
          />
        </div>
      </div>
      {/* ExerciseDetailPopup that shows up when isExerciseDetailOpen is true */}
      <ExerciseDetailPopup
        isOpen={isExerciseDetailOpen}
        onClose={closeExerciseDetail}
        exercise={exercise}
      />
    </div>
  );
};
