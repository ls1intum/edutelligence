import React, { useState, useEffect } from "react";
import { View, Pressable, ScrollView, TextInput, ActivityIndicator } from "react-native";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Text } from "@/components/ui/text";
import { Box } from "@/components/ui/box";
import { Button, ButtonText } from "@/components/ui/button";
import { Table, TableHeader, TableBody, TableHead, TableRow, TableData } from "@/components/ui/table";
import { Icon, TrashIcon, CheckIcon } from "@/components/ui/icon";
import { BaseModal } from "@/components/modals/base-modal";
import { ConfirmDeleteModal } from "@/components/modals/confirm-delete-modal";
import { API_BASE } from "@/components/statistics/constants";

const colStyles: Record<string, any> = {
    name: { width: "85%", minWidth: 150 },
    delete: { width: 48, alignItems: "flex-end" },
};

export function Models_tab({ teamId, canEdit, apiKey }: any) {
    const [allModels, setAllModels] = useState<any[]>([]);
    const [selectedModelIds, setSelectedModelIds] = useState<number[]>([]);
    const [loading, setLoading] = useState(true);
    const [addModelVisible, setAddModelVisible] = useState(false);
    const [modelSearch, setModelSearch] = useState("");
    const [stagedModelIds, setStagedModelIds] = useState<number[]>([]);
    const [deleteVisible, setDeleteVisible] = useState(false);
    const [modelToDelete, setModelToDelete] = useState<{ id: number; name: string } | null>(null);


    useEffect(() => {
        fetchData();
    }, [teamId]);

    const fetchData = async () => {
        setLoading(true);
        try {
            const modelsRes = await fetch(`${API_BASE}/logosdb/get_models`, {
                method: "POST",
                headers: { "logos-key": apiKey, "Content-Type": "application/json" },
                body: JSON.stringify({ logos_key: apiKey })
            });
            const modelsData = await modelsRes.json();
            setAllModels(Array.isArray(modelsData) ? modelsData : []);

            const permsRes = await fetch(`${API_BASE}/admin/teams/${teamId}/model-permissions`, {
                headers: { "logos-key": apiKey }
            });
            const activeIds = await permsRes.json();
            setSelectedModelIds(activeIds);
        } catch (e) {
            console.error("Failed to fetch model permissions", e);
        } finally {
            setLoading(false);
        }
    };

    const updatePermissionsInDB = async (newIds: number[]) => {
        try {
            const res = await fetch(`${API_BASE}/admin/teams/${teamId}/model-permissions`, {
                method: "PUT",
                headers: { "logos-key": apiKey, "Content-Type": "application/json" },
                body: JSON.stringify({ model_ids: newIds })
            });
            if (res.ok) {
                setSelectedModelIds(newIds);
            } else {
                alert("Failed to update permissions.");
            }
        } catch (e) {
            alert("Network error. Failed to update permissions.");
        }
    };

    const toggleStagedModel = (modelId: number) => {
        setStagedModelIds(prev =>
            prev.includes(modelId) ? prev.filter(id => id !== modelId) : [...prev, modelId]
        );
    };

    const handleAddStagedModels = () => {
        if (stagedModelIds.length === 0) return;
        updatePermissionsInDB([...selectedModelIds, ...stagedModelIds]);
        setAddModelVisible(false);
        setModelSearch("");
        setStagedModelIds([]);
    };

    const promptRemoveModel = (id: number, name: string) => {
        setModelToDelete({ id, name });
        setDeleteVisible(true);
    };

    const executeRemoveModel = () => {
        if (!modelToDelete) return;
        updatePermissionsInDB(selectedModelIds.filter(id => id !== modelToDelete.id));
        setDeleteVisible(false);
        setModelToDelete(null);
    };

    const teamModels = allModels.filter(m => selectedModelIds.includes(m.id));
    const availableModels = allModels.filter(m => !selectedModelIds.includes(m.id));
    const searchTerms = modelSearch.toLowerCase().trim().split(/\s+/);

    const filteredAvailableModels = modelSearch.trim()
        ? availableModels.filter(m => {
            const modelName = m?.name || "";
            const searchableText = modelName.toLowerCase();
            return searchTerms.every(term => searchableText.includes(term));
        })
        : availableModels;

    if (loading) {
        return (
            <VStack className="items-center justify-center p-8" space="lg">
                <ActivityIndicator size="large" color="#006DFF" />
                <Text className="text-typography-500">Loading models...</Text>
            </VStack>
        );
    }

    return (
        <VStack space="xl" style={{ marginTop: 16, paddingBottom: 40 }}>
            <VStack space="sm">
                <HStack style={{ justifyContent: "space-between", alignItems: "center" }}>
                    <Text style={{ fontWeight: "700", fontSize: 16 }}>Team Model Access</Text>
                    {canEdit && (
                        <Button size="sm" onPress={() => { setAddModelVisible(true); setStagedModelIds([]); }}>
                            <ButtonText>+ Add Models</ButtonText>
                        </Button>
                    )}
                </HStack>

                {teamModels.length === 0 ? (
                    <Text style={{ color: "#9ca3af", fontSize: 13, marginTop: 8 }}>
                        This team currently has no specific model permissions.
                    </Text>
                ) : (
                    <Box className="w-full overflow-hidden rounded-lg border border-outline-200 bg-secondary-200 p-2 mt-2">
                        <ScrollView horizontal contentContainerStyle={{ flexGrow: 1 }}>
                            <Box className="min-w-full">
                                <Table className="w-full">
                                    <TableHeader>
                                        <TableRow className="bg-secondary-200">
                                            <TableHead style={colStyles.name}>Model Name</TableHead>
                                            <TableHead style={colStyles.delete}>{""}</TableHead>
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {teamModels.map((model: any) => (
                                            <TableRow key={model.id} className="bg-secondary-200">
                                                <TableData style={colStyles.name}>
                                                    <Text style={{ fontWeight: "600", fontSize: 14 }}>{model.name || "Unnamed"}</Text>
                                                </TableData>
                                                <TableData style={colStyles.delete}>
                                                    {canEdit && (
                                                        <Pressable onPress={() => promptRemoveModel(model.id, model.name || "Unnamed")} style={{ padding: 8 }}>
                                                            <Icon as={TrashIcon} size="sm" className="text-typography-400" />
                                                        </Pressable>
                                                    )}
                                                </TableData>
                                            </TableRow>
                                        ))}
                                    </TableBody>
                                </Table>
                            </Box>
                        </ScrollView>
                    </Box>
                )}
            </VStack>

            <BaseModal visible={addModelVisible} onClose={() => { setAddModelVisible(false); setModelSearch(""); setStagedModelIds([]); }} maxWidth={800}>
                <VStack space="md" style={{ minWidth: 300 }}>
                    <Text style={{ fontWeight: "700", fontSize: 18 }}>Add Models to Team</Text>

                    <View style={{ borderWidth: 1, borderColor: "#e2e8f0", borderRadius: 8, paddingHorizontal: 10, paddingVertical: 9 }}>
                        <TextInput
                            placeholder="Search available models..."
                            value={modelSearch}
                            onChangeText={setModelSearch}
                            autoFocus
                            style={{ fontSize: 13, color: "#333", outlineStyle: "none" } as any}
                            placeholderTextColor="#aaa"
                        />
                    </View>

                    <ScrollView style={{ maxHeight: 400 }} keyboardShouldPersistTaps="handled">
                        <VStack space="xs" style={{ paddingVertical: 4 }}>
                            {filteredAvailableModels.map((model: any) => {
                                const isSelected = stagedModelIds.includes(model.id);
                                return (
                                    <Pressable
                                        key={model.id}
                                        onPress={() => toggleStagedModel(model.id)}
                                        style={{
                                            paddingHorizontal: 12, paddingVertical: 10,
                                            borderBottomWidth: 1, borderBottomColor: "#f3f4f6",
                                            flexDirection: "row", alignItems: "center",
                                            backgroundColor: "transparent"
                                        }}
                                    >
                                        <View style={{
                                            width: 20, height: 20, borderRadius: 4, borderWidth: 1,
                                            alignItems: "center", justifyContent: "center", marginRight: 14,
                                            borderColor: isSelected ? "#006DFF" : "#cbd5e1",
                                            backgroundColor: isSelected ? "#006DFF" : "transparent"
                                        }}>
                                            {isSelected && <Icon as={CheckIcon} size="xs" color="white" />}
                                        </View>

                                        <VStack style={{ flex: 1 }}>
                                            <Text style={{ fontWeight: "600", fontSize: 14, color: "#111827" }}>
                                                {model.name || `Model #${model.id}`}
                                            </Text>
                                            {model.description ? (
                                                <Text style={{ fontSize: 12, color: "#6b7280", marginTop: 2 }}>{model.description}</Text>
                                            ) : null}
                                        </VStack>
                                    </Pressable>
                                );
                            })}
                            {filteredAvailableModels.length === 0 && (
                                <Text style={{ paddingHorizontal: 10, paddingVertical: 16, color: "#9ca3af", fontSize: 13, textAlign: "center" }}>
                                    {availableModels.length === 0 ? "All models are already assigned to this team." : "No matching models found."}
                                </Text>
                            )}
                        </VStack>
                    </ScrollView>

                    <HStack space="md" style={{ justifyContent: "flex-end", marginTop: 8, paddingTop: 16, borderTopWidth: 1, borderTopColor: "#e2e8f0" }}>
                        <Button variant="outline" onPress={() => { setAddModelVisible(false); setModelSearch(""); setStagedModelIds([]); }}>
                            <ButtonText>Cancel</ButtonText>
                        </Button>
                        <Button
                            onPress={handleAddStagedModels}
                            disabled={stagedModelIds.length === 0}
                            style={{ opacity: stagedModelIds.length === 0 ? 0.5 : 1, minWidth: 150 }}
                        >
                            <ButtonText>Add Selected {stagedModelIds.length > 0 ? `(${stagedModelIds.length})` : ""}</ButtonText>
                        </Button>
                    </HStack>
                </VStack>
            </BaseModal>

            <ConfirmDeleteModal
                visible={deleteVisible}
                onClose={() => { setDeleteVisible(false); setModelToDelete(null); }}
                onConfirm={executeRemoveModel}
                title="Remove Model Access?"
                message={`Are you sure you want to remove access to "${modelToDelete?.name}" for this team?`}
            />

        </VStack>
    );
}
