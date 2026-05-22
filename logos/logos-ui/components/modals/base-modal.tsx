import React from "react";
import { Modal, Pressable } from "react-native";

export const OVERLAY = {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.4)",
    justifyContent: "center" as const,
    alignItems: "center" as const,
} as const;

export const CARD = {
    backgroundColor: "white",
    borderRadius: 12,
    padding: 24,
} as const;

export function BaseModal({ visible, onClose, children, maxWidth = 400 }: {
    visible: boolean;
    onClose: () => void;
    children: React.ReactNode;
    maxWidth?: number;
}) {
    return (
        <Modal visible={visible} transparent onRequestClose={onClose}>
            <Pressable style={OVERLAY} onPress={onClose}>
                <Pressable
                    style={[CARD, { maxWidth }]}
                    onPress={e => e.stopPropagation?.()}
                >
                    {children}
                </Pressable>
            </Pressable>
        </Modal>
    );
}
