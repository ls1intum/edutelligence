import React, { useEffect, useState } from 'react';
import Popup from "@/components/expert_evaluation/expert_view/popup";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import { InfoIconButton } from "@/components/expert_evaluation/expert_evaluation_buttons";

interface SingleChoiceLikertScaleProps {
    title: string;
    summary: string;
    description: string;
    passedValue: number | null;
    onLikertChange: (value: number) => void;
    isHighlighted: boolean;
}

export default function SingleChoiceLikertScale(singleChoiceLikertScale: SingleChoiceLikertScaleProps) {
    const {
        title,
        summary,
        description,
        passedValue,
        onLikertChange,
        isHighlighted,
    } = singleChoiceLikertScale;
    const [selectedValue, setSelectedValue] = useState<number | null>(null);
    const [isPopupOpen, setIsPopupOpen] = useState(false);

    const handleInfoClick = () => {
        setIsPopupOpen(true);
    };

    useEffect(() => {
        setSelectedValue(passedValue);
    }, [passedValue]);

    const handleChange = (value: number) => {
        setSelectedValue(value);
        onLikertChange(value);
    };

    const closePopup = () => {
        setIsPopupOpen(false);
    };

    const borderColors = [
        'border-gray-500',   // Not Applicable
        'border-red-600',    // Strongly Disagree
        'border-orange-500', // Disagree
        'border-yellow-400', // Neutral
        'border-green-400',  // Agree
        'border-green-700',  // Strongly Agree
    ];

    const selectedBgColors = [
        'bg-gray-200',
        'bg-red-200',
        'bg-orange-200',
        'bg-yellow-200',
        'bg-green-200',
        'bg-green-300',
    ];

    const scaleLabels = [
        'Not Ratable',
        'Strongly Disagree',
        'Disagree',
        'Neutral',
        'Agree',
        'Strongly Agree',
    ];

    return (
        <>
            {/* Title and Info Section */}
            <div className="flex items-center">
                <h3 className="text-sm font-semibold mr-1">{title}</h3>
                <InfoIconButton onClick={handleInfoClick} />
            </div>
            <Popup isOpen={isPopupOpen} onClose={closePopup} title="Information">
                <div className="prose prose-sm max-w-none">
                    <ReactMarkdown rehypePlugins={[rehypeRaw]}>
                        {description}
                    </ReactMarkdown>
                </div>
            </Popup>

            {/* Summary */}
            <p className="text-gray-700 text-xs mb-0.5">{summary}</p>

            {/* Single Choice Likert Scale */}
            <div className="flex justify-between w-full">
                {scaleLabels.map((label, index) => (
                    <button
                        key={index}
                        onClick={() => handleChange(index)}
                        className={`flex-1 text-xs py-0.5 text-center transition-colors duration-200 ease-in-out
                            ${selectedValue === index ? selectedBgColors[index] : isHighlighted ? 'bg-red-100' : 'bg-white'}
                            ${selectedValue === index ? `${borderColors[index]} border-l border-t border-r` : 'border-gray-300 border-l border-t border-r'}
                            border-b-4 ${borderColors[index]}
                            ${index === 0 ? 'rounded-l-md' : ''} ${index === scaleLabels.length - 1 ? 'rounded-r-md' : ''}`}
                    >
                        <span className={`block font-normal ${selectedValue === index ? 'underline' : ''}`}>
                            {label}
                        </span>
                    </button>
                ))}
            </div>
        </>
    );
};
