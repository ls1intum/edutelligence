import React, { useState } from 'react';
import TutorialPopup from "@/components/expert_evaluation/expert_view/tutorial_popup";
import background_image from "@/assets/evaluation_backgrounds/welcome-screen.jpeg";
import { PrimaryButton } from "@/components/expert_evaluation/expert_evaluation_buttons";
import { Exercise } from "@/model/exercise";

interface WelcomeScreenProps {
  exercise: Exercise;
  onClose: () => void;
}

export default function WelcomeScreen(welcomeScreenProps: WelcomeScreenProps) {
  const { exercise, onClose } = welcomeScreenProps;
  const [isTutorialOpen, setTutorialOpen] = useState(false);

  const closeTutorial = () => {
    setTutorialOpen(false);
    onClose();
  }

  const startTutorial = () => {
    setTutorialOpen(true);
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50"
      style={{
        backgroundImage: `url(${background_image.src})`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
      }}>
      <div className="bg-white p-8 rounded-lg shadow-lg max-w-lg w-full text-center">
        <h1 className="text-4xl font-bold mb-4">Welcome to the Expert Evaluation!</h1>
        <p className="text-lg mb-6">
          Thank you for taking the time to participate. Your input is valuable to us, and we appreciate your
          effort.
        </p>
        <PrimaryButton
          onClick={startTutorial}
          text="📚 Start Tutorial"
          className="px-6 py-3"
        />
      </div>
      <TutorialPopup isOpen={isTutorialOpen}
        onClose={closeTutorial}
        disableCloseOnOutsideClick={true}
        exercise={exercise} />
    </div>
  );
};
