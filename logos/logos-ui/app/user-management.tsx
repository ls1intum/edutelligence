import React, { useState, useEffect, useCallback } from "react";
import { Pressable, View, ActivityIndicator, ScrollView } from "react-native";
import { useAuth } from "@/components/auth-shell";
import { API_BASE, ROLE_COLORS, ROLE_LABELS, BasicTeam } from "@/components/statistics/constants";
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { Button, ButtonText } from "@/components/ui/button";
import { Table, TableHeader, TableBody, TableHead, TableRow, TableData } from "@/components/ui/table";
import { Icon, TrashIcon } from "@/components/ui/icon";
import { UserRole, ALL_ROLES } from "@/components/route-permissions";
import { BaseModal } from "@/components/modals/base-modal";
import { ConfirmDeleteModal } from "@/components/modals/confirm-delete-modal";
import { CreateUserModal, CreatedUser } from "@/components/modals/create-user-modal";
import { CsvImportModal } from "@/components/modals/csv-import-modal";
import { HStack } from "@/components/ui/hstack";

type User = {
    id: number;
    username: string;
    prename: string;
    name: string;
    email: string;
    role: UserRole;
    teams: BasicTeam[];
};

type RoleBadgeProps = {
    user: User;
    editable?: boolean;
    onPress?: () => void;
};

function RoleBadge({ user, editable = false, onPress }: RoleBadgeProps) {
    const badge = (
        <View style={{
            borderRadius: 8,
            paddingHorizontal: 8,
            paddingVertical: 4,
            borderWidth: 1,
            borderColor: ROLE_COLORS[user.role],
        }}>
            <Text style={{
                color: ROLE_COLORS[user.role],
                fontWeight: "600",
                fontSize: 12,
            }}>
                {ROLE_LABELS[user.role]}
            </Text>
        </View>
    );

    if (!editable) return badge;

    return (
        <Pressable onPress={onPress}>
            {badge}
        </Pressable>
    );
}

export default function UserManagement() {
    const { apiKey, role } = useAuth();
    const isLogosAdmin = role === "logos_admin";
    const [users, setUsers] = useState<User[]>([]);
    const [loading, setLoading] = useState(true);
    const [roleTarget, setRoleTarget] = useState<User | null>(null);
    const [deleteTarget, setDeleteTarget] = useState<User | null>(null);
    const [createVisible, setCreateVisible] = useState(false);
    const [importVisible, setImportVisible] = useState(false);

    const fetchUsers = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/users`, {
                headers: { "logos-key": apiKey }
            });
            if (!res.ok) throw new Error(`${res.status}`);
            const data = await res.json();
            setUsers(data);
        } catch (err) {
            console.error("Fetch error:", err);
        } finally {
            setLoading(false);
        }
    }, [apiKey]);

    useEffect(() => {
        fetchUsers();
    }, [fetchUsers]);

    const handleRoleChange = async (userId: number, newRole: UserRole) => {
        const previousUsers = [...users];
        setUsers(curr => curr.map(u => u.id === userId ? { ...u, role: newRole } : u));
        setRoleTarget(null);
        try {
            const res = await fetch(`${API_BASE}/users/${userId}/role`, {
                method: "PATCH",
                headers: { "logos-key": apiKey, "Content-Type": "application/json" },
                body: JSON.stringify({ role: newRole }),
            });
            if (!res.ok) throw new Error("Server rejected change");
        } catch (err) {
            setUsers(previousUsers);
        }
    };

    const handleDelete = async () => {
        if (!deleteTarget) return;
        const id = deleteTarget.id;
        const previousUsers = [...users];
        setUsers(curr => curr.filter(u => u.id !== id));
        setDeleteTarget(null);
        try {
            const res = await fetch(`${API_BASE}/users/${id}`, {
                method: "DELETE",
                headers: { "logos-key": apiKey },
            });
            if (!res.ok) throw new Error();
        } catch (err) {
            setUsers(previousUsers);
        }
    };

    return (
        <VStack className="w-full" space="lg">
            <VStack className="items-center space-y-1">
                <Text size="2xl" className="text-center font-bold text-black dark:text-white">
                    User Management
                </Text>
                <Text className="text-center text-gray-500 dark:text-gray-300">
                    Administrate users.
                </Text>
            </VStack>

            <HStack space="sm" className="self-end">
                <Button variant="outline" onPress={() => setImportVisible(true)}>
                    <ButtonText>Import CSV</ButtonText>
                </Button>
                <Button onPress={() => setCreateVisible(true)}>
                    <ButtonText>+ New User</ButtonText>
                </Button>
            </HStack>

            {loading ? (
                <VStack space="lg" className="items-center justify-center p-8">
                    <ActivityIndicator size="large" color="#006DFF" />
                    <Text className="mt-2 text-gray-500">Loading users...</Text>
                </VStack>
            ) : (
                <Box className="w-full overflow-hidden rounded-lg border border-outline-200 bg-secondary-200 p-2">
                    <ScrollView horizontal contentContainerStyle={{ flexGrow: 1 }}>
                        <Box className="min-w-full">
                            <Table className="w-full">
                                <TableHeader>
                                    <TableRow className="bg-secondary-200">
                                        <TableHead>Username</TableHead>
                                        <TableHead>Full Name</TableHead>
                                        <TableHead>Role</TableHead>
                                        <TableHead>Teams</TableHead>
                                        {isLogosAdmin && <TableHead>{""}</TableHead>}
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {users.map((user) => (
                                        <TableRow key={user.id} className="bg-secondary-200">
                                            <TableData><Text>{user.username}</Text></TableData>
                                            <TableData>
                                                <VStack>
                                                    <Text style={{ fontWeight: "500" }}>{user.prename} {user.name}</Text>
                                                    <Text style={{ fontSize: 12 }}>{user.email}</Text>
                                                </VStack>
                                            </TableData>
                                            <TableData>
                                                <RoleBadge
                                                    user={user}
                                                    editable={isLogosAdmin}
                                                    onPress={() => setRoleTarget(user)}
                                                />
                                            </TableData>
                                            <TableData>
                                                <Text>{user.teams.map(t => t.name).join(", ") || "-"}</Text>
                                            </TableData>
                                            {isLogosAdmin && user.username !== "root" && (
                                                <TableData>
                                                    <Pressable onPress={() => setDeleteTarget(user)} style={{ padding: 8 }}>
                                                        <Icon as={TrashIcon} size="sm" className="text-typography-400" />
                                                    </Pressable>
                                                </TableData>
                                            )}
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </Box>
                    </ScrollView>
                </Box>
            )}

            <RoleModal target={roleTarget} onClose={() => setRoleTarget(null)} onSelect={handleRoleChange} />
            <ConfirmDeleteModal
                visible={deleteTarget !== null}
                onClose={() => setDeleteTarget(null)}
                onConfirm={handleDelete}
                title="Delete User?"
                message={`Are you sure you want to remove ${deleteTarget?.username}? This action is permanent.`}
            />
            <CreateUserModal
                visible={createVisible}
                onClose={() => setCreateVisible(false)}
                onCreated={(user: CreatedUser) => setUsers(prev => [user as User, ...prev])}
                apiKey={apiKey}
                showRoleSelector={isLogosAdmin}
                showTeamPicker={true}
                preselectedTeamIds={[]}
            />
            <CsvImportModal
                visible={importVisible}
                onClose={() => setImportVisible(false)}
                apiKey={apiKey}
                onImported={fetchUsers}
            />
        </VStack>
    );
}

function RoleModal({ target, onClose, onSelect }: any) {
    if (!target) return null;
    return (
        <BaseModal visible={target} onClose={onClose} maxWidth={400}>
            <Text style={{ fontWeight: "700", marginBottom: 12 }}>Change Role</Text>
            {ALL_ROLES.map(role => (
                <Pressable key={role} onPress={() => onSelect(target.id, role)}
                    style={{ flexDirection: "row", alignItems: "center", padding: 8, borderRadius: 8, marginBottom: 4, borderWidth: 1, borderColor: target.role === role ? ROLE_COLORS[role] : "transparent" }}>
                    <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: ROLE_COLORS[role], marginRight: 10 }} />
                    <Text style={{ color: target.role === role ? ROLE_COLORS[role] : "#999", fontSize: 14 }}>{ROLE_LABELS[role]}</Text>
                </Pressable>
            ))}
        </BaseModal>
    );
}
