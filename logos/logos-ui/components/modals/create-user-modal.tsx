import React, { useState } from "react";
import { Modal, Pressable, Platform, ScrollView, TextInput, View } from "react-native";
import { API_BASE, ROLE_COLORS, ROLE_LABELS, BasicTeam } from "@/components/statistics/constants";
import { OVERLAY, CARD } from "./base-modal";
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Button, ButtonText } from "@/components/ui/button";
import { Input, InputField } from "@/components/ui/input";
import { UserRole, ALL_ROLES } from "@/components/route-permissions";

export type CreatedUser = {
    id: number;
    username: string;
    prename: string;
    name: string;
    email: string;
    role: UserRole;
    teams: BasicTeam[];
    logos_keys?: string[];
};

type Props = {
    visible: boolean;
    onClose: () => void;
    onCreated: (user: CreatedUser) => void;
    apiKey: string;
    showRoleSelector: boolean;
    showTeamPicker: boolean;
    preselectedTeamIds?: number[];
};

const EMPTY_FORM = {
    prename: "",
    name: "",
    email: "",
    role: "app_developer" as UserRole,
};

export function CreateUserModal({ visible, onClose, onCreated, apiKey, showRoleSelector, showTeamPicker, preselectedTeamIds = [] }: Props) {
    const [form, setForm] = useState(EMPTY_FORM);
    const [loading, setLoading] = useState(false);
    const [generatedKeys, setGeneratedKeys] = useState<string[]>([]);
    const [copied, setCopied] = useState(false);
    const [error, setError] = useState("");
    const [teams, setTeams] = useState<BasicTeam[]>([]);
    const [selectedTeamIds, setSelectedTeamIds] = useState<number[]>([]);
    const [teamPickerOpen, setTeamPickerOpen] = useState(false);
    const [teamSearch, setTeamSearch] = useState("");
    const [generatedUsername, setGeneratedUsername] = useState("");

    React.useEffect(() => {
        if (showTeamPicker && visible) {
            fetch(`${API_BASE}/teams`, { headers: { Authorization: `Bearer ${apiKey}` } })
                .then(r => r.ok ? r.json() : [])
                .then(data => {
                    setTeams(data.filter((t: any) => t.name !== "default" && t.is_caller_owner === true));
                })
                .catch(() => setTeams([]));
        }
    }, [visible, showTeamPicker, apiKey]);

    const isAnyFieldEmpty = !form.prename.trim() || !form.name.trim() || !form.email.trim();

    const handleCreate = async () => {
        setError("");
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
            setError("The email format is invalid.");
            return;
        }
        setLoading(true);
        const teamIds = showTeamPicker ? selectedTeamIds : preselectedTeamIds;
        try {
            const res = await fetch(`${API_BASE}/users`, {
                method: "POST",
                headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
                body: JSON.stringify({ ...form, team_ids: teamIds }),
            });
            const data = await res.json();
            if (res.ok) {
                setGeneratedKeys(data.logos_keys || []);
                setGeneratedUsername(data.username);
                onCreated(data as CreatedUser);
            } else {
                setError(data.detail || "This email is already taken.");
            }
        } catch {
            setError("Connection failed. Please try again.");
        } finally {
            setLoading(false);
        }
    };

    const handleCopy = async () => {
        const textToCopy = generatedKeys.join("\n");
        if (Platform.OS === "web") await navigator.clipboard.writeText(textToCopy);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };

    const closeAndReset = () => {
        setForm(EMPTY_FORM);
        setGeneratedKeys([]);
        setGeneratedUsername("");
        setError("");
        setSelectedTeamIds([]);
        setTeamPickerOpen(false);
        setTeamSearch("");
        onClose();
    };

    const filteredTeams = teams.filter(t =>
        t.name.toLowerCase().includes(teamSearch.toLowerCase())
    );

    const selectedTeamNames = teams
        .filter(t => selectedTeamIds.includes(t.id))
        .map(t => t.name)
        .join(", ");

    const toggleTeam = (id: number) => {
        setSelectedTeamIds(prev =>
            prev.includes(id) ? prev.filter(t => t !== id) : [...prev, id]
        );
    };

    return (
        <Modal visible={visible} transparent onRequestClose={generatedKeys.length > 0 ? undefined : closeAndReset}>
            <Pressable style={OVERLAY} onPress={generatedKeys.length > 0 ? undefined : closeAndReset}>
                <Pressable style={[CARD, { maxWidth: 380, width: "100%" }]} onPress={e => e.stopPropagation?.()}>
                    {generatedKeys.length === 0 ? (
                        <VStack space="md">
                            <Text style={{ fontWeight: "700", fontSize: 18 }}>Create New User</Text>
                            <Input><InputField placeholder="First Name" value={form.prename} onChangeText={v => setForm(f => ({ ...f, prename: v }))} /></Input>
                            <Input><InputField placeholder="Last Name" value={form.name} onChangeText={v => setForm(f => ({ ...f, name: v }))} /></Input>
                            <Input><InputField placeholder="Email" value={form.email} autoCapitalize="none" onChangeText={v => setForm(f => ({ ...f, email: v }))} /></Input>
                            {error ? <Text style={{ color: "#e63535", fontSize: 12, fontWeight: "500" }}>{error}</Text> : null}
                            {showRoleSelector && (
                                <HStack space="xs" className="flex-wrap mt-2">
                                    {ALL_ROLES.map(role => (
                                        <Pressable key={role} onPress={() => setForm(f => ({ ...f, role }))}
                                            style={{ paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, borderWidth: 1, borderColor: form.role === role ? ROLE_COLORS[role] : "#eee" }}>
                                            <Text style={{ fontSize: 11, fontWeight: "600", color: form.role === role ? ROLE_COLORS[role] : "#999" }}>{ROLE_LABELS[role]}</Text>
                                        </Pressable>
                                    ))}
                                </HStack>
                            )}
                            {showTeamPicker && teams.length > 0 && (
                                <VStack space="xs">
                                    <Text style={{ fontSize: 13, fontWeight: "600", color: "#555" }}>Teams (optional)</Text>
                                    <Pressable
                                        onPress={() => setTeamPickerOpen(o => !o)}
                                        style={{ borderWidth: 1, borderColor: "#e2e8f0", borderRadius: 8, padding: 10, flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}
                                    >
                                        <Text style={{ fontSize: 14, color: selectedTeamNames ? "#000" : "#aaa", flex: 1 }} numberOfLines={1}>
                                            {selectedTeamNames || "Select teams..."}
                                        </Text>
                                        <Text style={{ color: "#aaa", fontSize: 11 }}>{teamPickerOpen ? "▲" : "▼"}</Text>
                                    </Pressable>
                                    {teamPickerOpen && (
                                        <View style={{ borderWidth: 1, borderColor: "#e2e8f0", borderRadius: 8, maxHeight: 200, overflow: "hidden" }}>
                                            <View style={{ borderBottomWidth: 1, borderBottomColor: "#e2e8f0", paddingHorizontal: 10, paddingVertical: 9 }}>
                                                <TextInput
                                                    placeholder="Search teams..."
                                                    value={teamSearch}
                                                    onChangeText={setTeamSearch}
                                                    style={{
                                                        fontSize: 13,
                                                        color: "#333",
                                                        outlineStyle: "none",
                                                    } as any}
                                                    placeholderTextColor="#aaa"
                                                />
                                            </View>
                                            <ScrollView keyboardShouldPersistTaps="handled">
                                                {filteredTeams.map(team => {
                                                    const selected = selectedTeamIds.includes(team.id);
                                                    return (
                                                        <Pressable
                                                            key={team.id}
                                                            onPress={() => toggleTeam(team.id)}
                                                            style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 10, paddingVertical: 9, borderBottomWidth: 1, borderBottomColor: "#f1f5f9" }}
                                                        >
                                                            <View style={{ width: 16, height: 16, borderRadius: 4, borderWidth: 1.5, borderColor: selected ? "#006DFF" : "#ccc", backgroundColor: selected ? "#006DFF" : "transparent", marginRight: 10, justifyContent: "center", alignItems: "center" }}>
                                                                {selected && <Text style={{ color: "white", fontSize: 10, lineHeight: 14 }}>✓</Text>}
                                                            </View>
                                                            <Text style={{ fontSize: 13, color: "#333" }}>{team.name}</Text>
                                                        </Pressable>
                                                    );
                                                })}
                                            </ScrollView>
                                        </View>
                                    )}
                                </VStack>
                            )}
                            <HStack space="md" className="justify-end mt-4">
                                <Button variant="outline" onPress={closeAndReset}><ButtonText>Cancel</ButtonText></Button>
                                <Button onPress={handleCreate} disabled={isAnyFieldEmpty || loading} style={{ opacity: (isAnyFieldEmpty || loading) ? 0.5 : 1 }}>
                                    <ButtonText>Create</ButtonText>
                                </Button>
                            </HStack>
                        </VStack>
                    ) : (
                        <VStack space="md">
                            <Text style={{ fontWeight: "700", fontSize: 18 }}>User Created!</Text>
                            <Text style={{ fontSize: 14 }}>Username: {generatedUsername}</Text>
                            <Text style={{ fontSize: 14 }}>Copy the API keys now, they won't be shown again:</Text>
                            <ScrollView style={{ maxHeight: 150 }} indicatorStyle="black">
                                <VStack space="sm">
                                    {generatedKeys.map((key, index) => (
                                        <Box key={index} className="bg-gray-100 p-3 rounded-lg border border-gray-200">
                                            <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                                                <Text selectable style={{ fontFamily: "monospace", fontSize: 13 }}>
                                                    {key}
                                                </Text>
                                            </ScrollView>
                                        </Box>
                                    ))}
                                </VStack>
                            </ScrollView>

                            <HStack space="md" className="justify-end mt-2">
                                <Button variant="outline" onPress={handleCopy}>
                                    <ButtonText>{copied ? "Copied!" : "Copy All Keys"}</ButtonText>
                                </Button>
                                <Button onPress={closeAndReset}><ButtonText>Done</ButtonText></Button>
                            </HStack>
                        </VStack>
                    )}
                </Pressable>
            </Pressable>
        </Modal>
    );
}
