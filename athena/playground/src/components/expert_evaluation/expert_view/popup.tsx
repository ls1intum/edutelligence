import React, { ReactNode } from 'react';

interface PopupProps {
    isOpen: boolean;
    onClose: () => void;
    title: string;
    children: ReactNode;
    disableCloseOnOutsideClick?: boolean;
}

export default function Popup(popupProps: PopupProps) {
    const { isOpen, onClose, title, children, disableCloseOnOutsideClick } = popupProps;
    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 bg-black bg-opacity-50 flex items-center justify-center p-6"
            onClick={() => {
                if (!disableCloseOnOutsideClick) {
                    onClose();
                }
            }}
        >
            <div
                className="bg-white p-6 rounded-lg shadow-lg max-w-7xl max-h-full relative"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex justify-between items-center mb-4">
                    <h1 className="text-xl font-semibold">{title}</h1>
                    <button
                        className="text-gray-500 hover:text-gray-700 focus:outline-none"
                        onClick={onClose}
                    >
                        ╳
                    </button>
                </div>
                {/* Scrollable content wrapper */}
                <div className="overflow-y-auto max-h-[80vh]">
                    {children}
                </div>
            </div>
        </div>
    );
};
