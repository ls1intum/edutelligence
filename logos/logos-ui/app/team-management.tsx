import React, { useState, useEffect, useCallback } from "react";
import { Pressable, ActivityIndicator, ScrollView } from "react-native";
import { useRouter } from "expo-router";
import { useAuth } from "@/components/auth-shell";
import { API_BASE, User } from "@/components/statistics/constants";
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Button, ButtonText } from "@/components/ui/button";
import { Input, InputField } from "@/components/ui/input";
import { Table, TableHeader, TableBody, TableHead, TableRow, TableData } from "@/components/ui/table";
import { Icon, TrashIcon } from "@/components/ui/icon";
import { BaseModal } from "@/components/modals/base-modal";
import { ConfirmDeleteModal } from "@/components/modals/confirm-delete-modal";

type TeamOwner = { id: number; username: string };
type Team = {
    id: number;
    name: string;
    owners: TeamOwner[];
    member_count: number;
    model_count: number;
    default_cloud_rpm_limit: number | null;
    default_cloud_tpm_limit: number | null;
    default_local_rpm_limit: number | null;
    default_local_tpm_limit: number | null;
    is_caller_owner?: boolean;
};

export default function TeamManagement() {
    const { apiKey, role } = useAuth();
    const router = useRouter();
    const isLogosAdmin = role === "logos_admin";

    const [teams, setTeams] = useState<Team[]>([]);
    const [loading, setLoading] = useState(true);
    const [adminUsers, setAdminUsers] = useState<User[]>([]);
    const [createVisible, setCreateVisible] = useState(false);
    const [deleteTarget, setDeleteTarget] = useState<Team | null>(null);

    const fetchTeams = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/teams`, { headers: { Authorization: `Bearer ${apiKey}` } });
            if (!res.ok) throw new Error();
            setTeams(await res.json());
        } catch {
        } finally {
            setLoading(false);
        }
    }, [apiKey]);

    useEffect(() => { fetchTeams(); }, [fetchTeams]);

    useEffect(() => {
        if (!isLogosAdmin) return;
        fetch(`${API_BASE}/users/admins`, { headers: { Authorization: `Bearer ${apiKey}` } })
            .then(r => r.ok ? r.json() : [])
            .then(setAdminUsers)
            .catch(() => setAdminUsers([]));
    }, [apiKey, isLogosAdmin]);

    const handleDelete = async () => {
        if (!deleteTarget) return;
        const id = deleteTarget.id;
        setDeleteTarget(null);
        setTeams(prev => prev.filter(t => t.id !== id));
        try {
            await fetch(`${API_BASE}/teams/${id}`, {
                method: "DELETE",
                headers: { Authorization: `Bearer ${apiKey}` },
            });
        } catch {
            fetchTeams();
        }
    };

    return (
        <VStack className="w-full" space="lg">
            <VStack className="items-center space-y-1">
                <Text size="2xl" className="text-center font-bold text-black dark:text-white">
                    Team Management
                </Text>
                <Text className="text-center text-gray-500 dark:text-gray-300">
                    Manage teams and their members.
                </Text>
            </VStack>
            <Box className="self-end">
                <Button onPress={() => setCreateVisible(true)}>
                    <ButtonText>+ New Team</ButtonText>
                </Button>
            </Box>
            {loading ? (
                <VStack space="lg" className="items-center justify-center p-8">
                    <ActivityIndicator size="large" color="#006DFF" />
                    <Text className="mt-2 text-gray-500">Loading teams...</Text>
                </VStack>            ) : teams.length === 0 ? (
                <Text className="text-center text-gray-400 mt-8">No teams yet.</Text>
            ) : (
                <Box className="w-full overflow-hidden rounded-lg border border-outline-200 bg-secondary-200 p-2">
                    <ScrollView horizontal contentContainerStyle={{ flexGrow: 1 }}>
                        <Box className="min-w-full">
                            <Table className="w-full">
                                <TableHeader>
                                    <TableRow className="bg-secondary-200">
                                        <TableHead>Name</TableHead>
                                        <TableHead>Owners</TableHead>
                                        <TableHead>Members</TableHead>
                                        <TableHead>Cloud Limits</TableHead>
                                        <TableHead>Local Limits</TableHead>
                                        <TableHead>Models</TableHead>
                                        <TableHead>{""}</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {teams.map(team => {
                                        const goToDetail = () => router.push(`/team-management/${team.id}` as any);
                                        return (
                                            <TableRow key={team.id} className="bg-secondary-200">
                                                <TableData>
                                                    <Pressable onPress={goToDetail} style={{ flex: 1 }}>
                                                        <Text style={{ fontWeight: "500" }}>{team.name}</Text>
                                                    </Pressable>
                                                </TableData>
                                                <TableData>
                                                    <Pressable onPress={goToDetail} style={{ flex: 1 }}>
                                                        <Text>{team.owners.map(o => o.username).join(", ") || "-"}</Text>
                                                    </Pressable>
                                                </TableData>
                                                <TableData>
                                                    <Pressable onPress={goToDetail} style={{ flex: 1 }}>
                                                        <Text>{String(team.member_count)}</Text>
                                                    </Pressable>
                                                </TableData>
                                                <TableData>
                                                    <Pressable onPress={goToDetail} style={{ flex: 1 }}>
                                                        <Text style={{ fontSize: 13 }}>
                                                            {team.default_cloud_rpm_limit ?? "∞"} RPM / {team.default_cloud_tpm_limit ? (team.default_cloud_tpm_limit >= 1000 ? `${Math.round(team.default_cloud_tpm_limit / 1000)}k` : String(team.default_cloud_tpm_limit)) : "∞"} TPM
                                                        </Text>
                                                    </Pressable>
                                                </TableData>
                                                <TableData>
                                                    <Pressable onPress={goToDetail} style={{ flex: 1 }}>
                                                        <Text style={{ fontSize: 13 }}>
                                                            {team.default_local_rpm_limit ?? "∞"} RPM / {team.default_local_tpm_limit ? (team.default_local_tpm_limit >= 1000 ? `${Math.round(team.default_local_tpm_limit / 1000)}k` : String(team.default_local_tpm_limit)) : "∞"} TPM
                                                        </Text>
                                                    </Pressable>
                                                </TableData>
                                                <TableData>
                                                    <Pressable onPress={goToDetail} style={{ flex: 1 }}>
                                                        <Text style={{ fontSize: 13 }}>{team.model_count ?? 0}</Text>
                                                    </Pressable>
                                                </TableData>
                                                <TableData style={{ width: 48, alignItems: "flex-end" }}>
                                                    {(isLogosAdmin || team.is_caller_owner) && (
                                                        <Pressable onPress={() => setDeleteTarget(team)} style={{ padding: 8 }}>
                                                            <Icon as={TrashIcon} size="sm" className="text-typography-400" />
                                                        </Pressable>
                                                    )}
                                                </TableData>
                                            </TableRow>
                                        );
                                    })}
                                </TableBody>
                            </Table>
                        </Box>
                    </ScrollView>
                </Box>
            )}

            <CreateTeamModal
                visible={createVisible}
                onClose={() => setCreateVisible(false)}
                onCreated={() => { fetchTeams(); setCreateVisible(false); }}
                apiKey={apiKey}
                isLogosAdmin={isLogosAdmin}
                adminUsers={adminUsers}
            />

            <ConfirmDeleteModal
                visible={!!deleteTarget}
                onClose={() => setDeleteTarget(null)}
                onConfirm={handleDelete}
                title="Delete Team?"
                message={`Are you sure you want to remove "${deleteTarget?.name}"? This action is permanent.`}
            />
        </VStack>
    );
}

function CreateTeamModal({ visible, onClose, onCreated, apiKey, isLogosAdmin, adminUsers }: {
    visible: boolean;
    onClose: () => void;
    onCreated: () => void;
    apiKey: string;
    isLogosAdmin: boolean;
    adminUsers: User[];
}) {
    const [name, setName] = useState("");
    const [selectedOwnerIds, setSelectedOwnerIds] = useState<number[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");

    const closeAndReset = () => {
        setName("");
        setSelectedOwnerIds([]);
        setError("");
        onClose();
    };

    const toggleOwner = (id: number) => {
        setSelectedOwnerIds(prev =>
            prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
        );
    };

    const handleCreate = async () => {
        setError("");
        if (!name.trim()) { setError("Team name is required."); return; }
        setLoading(true);
        try {
            const res = await fetch(`${API_BASE}/teams`, {
                method: "POST",
                headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
                body: JSON.stringify({ name: name.trim(), owner_ids: selectedOwnerIds }),
            });
            const data = await res.json();
            if (res.ok) {
                setName("");
                setSelectedOwnerIds([]);
                onCreated();
            } else {
                setError(data.detail || "Failed to create team.");
            }
        } catch {
            setError("Connection failed. Please try again.");
        } finally {
            setLoading(false);
        }
    };

    return (
        <BaseModal visible={visible} onClose={closeAndReset} maxWidth={420}>
            <VStack space="md">
                <Text style={{ fontWeight: "700", fontSize: 18 }}>Create New Team</Text>
                <Input>
                    <InputField placeholder="Team Name" value={name} onChangeText={setName} />
                </Input>
                {isLogosAdmin && adminUsers.length > 0 && (
                    <VStack space="xs">
                        <Text style={{ fontSize: 13, fontWeight: "600", color: "#555" }}>Owner(s)</Text>
                        <HStack space="xs" className="flex-wrap">
                            {adminUsers.map(u => {
                                const selected = selectedOwnerIds.includes(u.id);
                                return (
                                    <Pressable key={u.id} onPress={() => toggleOwner(u.id)}
                                        style={{ paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, borderWidth: 1, borderColor: selected ? "#006DFF" : "#eee", marginBottom: 4 }}>
                                        <Text style={{ fontSize: 11, fontWeight: "600", color: selected ? "#006DFF" : "#999" }}>{u.username}</Text>
                                    </Pressable>
                                );
                            })}
                        </HStack>
                    </VStack>
                )}
                {error ? <Text style={{ color: "#e63535", fontSize: 12, fontWeight: "500" }}>{error}</Text> : null}
                <HStack space="md" className="justify-end mt-4">
                    <Button variant="outline" onPress={closeAndReset}>
                        <ButtonText>Cancel</ButtonText>
                    </Button>
                    <Button onPress={handleCreate} disabled={!name.trim() || loading} style={{ opacity: (!name.trim() || loading) ? 0.5 : 1 }}>
                        <ButtonText>Create</ButtonText>
                    </Button>
                </HStack>
            </VStack>
        </BaseModal>
    );
}
