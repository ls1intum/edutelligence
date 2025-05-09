import React from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCircleInfo } from '@fortawesome/free-solid-svg-icons';

const buttonBase = "px-4 py-2 rounded focus:outline-none transition-all";
const buttonPrimary = `${buttonBase} bg-blue-500 text-white hover:bg-blue-600`;
const buttonSecondary = `${buttonBase} bg-gray-300 text-gray-700 hover:bg-gray-400`;
const buttonFinish = `${buttonBase} bg-green-600 text-white hover:bg-green-700`;


interface NextButtonProps {
    onClick?: () => void;
    isFinish?: boolean;
    isInline?: boolean;
    className?: string;
}

export function NextButton(nextButtonProps: NextButtonProps) {
    const { onClick, isFinish, isInline, className } = nextButtonProps;
    return <button
        onClick={onClick}
        className={`${isFinish ? buttonFinish : buttonPrimary}  ${isInline ? 'inline-block' : 'w-full'} ${className}`}
    >
        {isFinish ? 'Finish 🏁' : 'Next ➡️'}
    </button>
}


interface SecondaryButtonProps {
    onClick?: () => void;
    isInline?: boolean;
    className?: string;
    text: string;
    isDisabled?: boolean;
}

export function SecondaryButton(secondaryButtonProps: SecondaryButtonProps) {
    const { onClick, isInline, className, text, isDisabled } = secondaryButtonProps;
    return <button
        onClick={onClick}
        className={`${buttonSecondary} ${isInline ? 'inline-block' : ''} ${className}`}
        disabled={isDisabled}
    >
        {text}
    </button>
}


interface PrimaryButtonProps {
    onClick?: () => void;
    isInline?: boolean;
    isDisabled?: boolean,
    className?: string;
    text: string;
}

export function PrimaryButton(primaryButtonProps: PrimaryButtonProps) {
    const { onClick, isInline, isDisabled, className, text } = primaryButtonProps;
    return <button
        onClick={onClick}
        className={`${buttonPrimary} ${isInline ? 'inline-block' : ''} ${className}`}
        disabled={isDisabled}
    >
        {text}
    </button>
}


interface InfoIconButtonProps {
    onClick?: () => void;
    className?: string;
}

export function InfoIconButton(infoIconButtonProps: InfoIconButtonProps) {
    const { onClick, className } = infoIconButtonProps;
    return <span
        onClick={onClick}
        className={`text-gray-400 cursor-pointer hover:text-gray-600 ${className}`}
        role="img"
        aria-label="info"
    >
        <FontAwesomeIcon icon={faCircleInfo} />
    </span>
}
