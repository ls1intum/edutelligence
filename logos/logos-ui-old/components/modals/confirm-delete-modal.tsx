import React from "react";
import { BaseModal } from "./base-modal";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Button, ButtonText } from "@/components/ui/button";

export function ConfirmDeleteModal({ visible, onClose, onConfirm, title, message }: {
    visible: boolean;
    onClose: () => void;
    onConfirm: () => void;
    title: string;
    message: string;
}) {
    return (
        <BaseModal visible={visible} onClose={onClose} maxWidth={400}>
            <VStack space="md">
                <Text style={{ fontWeight: "700", fontSize: 16 }}>{title}</Text>
                <Text style={{ fontSize: 14 }}>{message}</Text>
                <HStack space="md" className="justify-end">
                    <Button variant="outline" onPress={onClose}>
                        <ButtonText>Cancel</ButtonText>
                    </Button>
                    <Button action="negative" onPress={onConfirm}>
                        <ButtonText>Delete</ButtonText>
                    </Button>
                </HStack>
            </VStack>
        </BaseModal>
    );
}
