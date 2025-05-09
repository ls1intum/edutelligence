import React from 'react';
import Popup from "@/components/expert_evaluation/expert_view/popup";
import ExerciseDetail from "@/components/details/exercise_detail";
import { Exercise } from "@/model/exercise";

interface ExerciseDetailPopupProps {
  isOpen: boolean;
  onClose: () => void;
  exercise: Exercise;
}

export default function ExerciseDetailPopup(exerciseDetailPopupProps: ExerciseDetailPopupProps) {
  const { isOpen, onClose, exercise } = exerciseDetailPopupProps;

  return (
    <Popup isOpen={isOpen} onClose={onClose} title={`Exercise Details: ${exercise.title}`}>
      <ExerciseDetail exercise={exercise} hideDisclosure={true} openedInitially={true} />
    </Popup>
  );
};
