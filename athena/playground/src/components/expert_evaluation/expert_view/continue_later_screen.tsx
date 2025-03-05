import React from 'react';
import background_image from "@/assets/evaluation_backgrounds/save-progress.jpeg";
import { PrimaryButton } from "@/components/expert_evaluation/expert_evaluation_buttons";


interface ContinueLaterScreenProps {
  onClose: () => void;
}

export default function ContinueLaterScreen(continueLaterScreenProps: ContinueLaterScreenProps) {
  const { onClose } = continueLaterScreenProps;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50"
      style={{
        backgroundImage: `url(${background_image.src})`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
      }}
    >
      <div className="bg-white p-8 rounded-lg shadow-lg max-w-lg w-full text-center">
        <h1 className="text-4xl font-bold mb-4">Continue Later</h1>
        <p className="text-lg mb-6">
          Your progress has been saved. You can continue the evaluation later using the same link.
        </p>
        <PrimaryButton
          onClick={onClose}
          text="Continue Evaluation"
          className="px-6 py-3 ml-4"
        />
      </div>
    </div>
  );
};
