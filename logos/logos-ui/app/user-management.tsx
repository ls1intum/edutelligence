import React, { useState, useEffect, useCallback } from "react";
import { Modal, Pressable, View, ActivityIndicator, Platform, ScrollView } from "react-native";
import { useAuth } from "@/components/auth-shell";
import { API_BASE, ROLES_PALETTE } from "@/components/statistics/constants";
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Button, ButtonText } from "@/components/ui/button";
import { Input, InputField } from "@/components/ui/input";
import { Table, TableHeader, TableBody, TableHead, TableRow, TableData } from "@/components/ui/table";
import { Icon, TrashIcon } from "@/components/ui/icon";
import { UserRole, ALL_ROLES } from "@/components/route-permissions";

type Team = {
    id: number;
    name: string;
};

type User = {
    id: number;
    username: string;
    prename: string;
    name: string;
    email: string;
    role: UserRole;
    teams: Team[];
};

type CreateForm = {
    username: string;
    prename: string;
    name: string;
    email: string;
    role: UserRole;
};

const ROLE_COLORS: Record<UserRole, string> = {
    logos_admin: ROLES_PALETTE.logos_admin,
    app_admin: ROLES_PALETTE.app_admin,
    app_developer: ROLES_PALETTE.app_developer,
};

const ROLE_LABELS: Record<UserRole, string> = {
    logos_admin: "Logos Admin",
    app_admin: "App Admin",
    app_developer: "App Developer",
};

const EMPTY_FORM: CreateForm = {
    prename: "",
    name: "",
    username: "",
    email: "",
    role: "app_developer",
};

const MODAL_STYLES = {
    overlay: {
        flex: 1,
        backgroundColor: "rgba(0,0,0,0.4)",
        justifyContent: "center",
        alignItems: "center",
    },
    card: {
        backgroundColor: "white",
        borderRadius: 12,
        padding: 24,
    },
    description: {
        fontSize: 14,
        marginBottom: 16,
    }
} as const;

function BaseModal({ visible, onClose, children, maxWidth = 400 }: any) {
    return (
        <Modal
            visible={visible}
            transparent
            onRequestClose={onClose}
        >
            <Pressable style={MODAL_STYLES.overlay} onPress={onClose}>
                <Pressable
                    style={[MODAL_STYLES.card, { maxWidth }]}
                    onPress={(e) => e.stopPropagation?.()}
                >
                    {children}
                </Pressable>
            </Pressable>
        </Modal>
    );
}

export default function UserManagement() {
    const { apiKey } = useAuth();
    const [users, setUsers] = useState<User[]>([]);
    const [loading, setLoading] = useState(true);
    const [roleTarget, setRoleTarget] = useState<User | null>(null);
    const [deleteTarget, setDeleteTarget] = useState<User | null>(null);
    const [createVisible, setCreateVisible] = useState(false);

    const fetchUsers = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/users`, {
                headers: { "logos-key": apiKey }
            });
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
                    Administrate Users.
                </Text>
            </VStack>

            {!loading && (
                <HStack space="xl" className="justify-center">
                    <VStack className="min-w-[120px] items-center rounded-xl border border-outline-200 bg-background-50 p-4 dark:border-none">
                        <Text size="xl" className="font-bold text-black dark:text-white">
                            {users.length}
                        </Text>
                        <Text size="sm" className="mt-1 text-black dark:text-white">
                            Users
                        </Text>
                    </VStack>
                </HStack>
            )}

            <Box className="self-end">
                <Button onPress={() => setCreateVisible(true)}>
                    <ButtonText>+ New User</ButtonText>
                </Button>
            </Box>

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
                                        <TableHead>{""}</TableHead>
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
                                                <Pressable onPress={() => setRoleTarget(user)}>
                                                    <View style={{
                                                        borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4,
                                                        borderWidth: 1, borderColor: ROLE_COLORS[user.role]
                                                    }}>
                                                        <Text style={{ color: ROLE_COLORS[user.role], fontWeight: "600", fontSize: 12 }}>
                                                            {ROLE_LABELS[user.role]}
                                                        </Text>
                                                    </View>
                                                </Pressable>
                                            </TableData>
                                            <TableData>
                                                <Text>{user.teams.map(t => t.name).join(", ") || "-"}</Text>
                                            </TableData>
                                            <TableData>
                                                <Pressable onPress={() => setDeleteTarget(user)} style={{ padding: 8 }}>
                                                    <Icon as={TrashIcon} size="sm" className="text-typography-400" />
                                                </Pressable>
                                            </TableData>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </Box>
                    </ScrollView>
                </Box>
            )}

            <RoleModal target={roleTarget} onClose={() => setRoleTarget(null)} onSelect={handleRoleChange} />
            <DeleteModal target={deleteTarget} onClose={() => setDeleteTarget(null)} onConfirm={handleDelete} />
            <CreateUserModal
                visible={createVisible}
                onClose={() => setCreateVisible(false)}
                onCreated={(user: User) => setUsers(prev => [user, ...prev])}
                apiKey={apiKey}
            />
        </VStack>
    );
}

function CreateUserModal({ visible, onClose, onCreated, apiKey }: any) {
    const [form, setForm] = useState<CreateForm>(EMPTY_FORM);
    const [loading, setLoading] = useState(false);
    const [generatedKey, setGeneratedKey] = useState("");
    const [copied, setCopied] = useState(false);
    const [error, setError] = useState("");

    const isAnyFieldEmpty = !form.prename.trim() || !form.name.trim() || !form.username.trim() || !form.email.trim();

    const handleCreate = async () => {
        setError("");
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
            setError("The email format is invalid.");
            return;
        }
        setLoading(true);
        try {
            const res = await fetch(`${API_BASE}/users`, {
                method: "POST",
                headers: { "logos-key": apiKey, "Content-Type": "application/json" },
                body: JSON.stringify(form),
            });
            const data = await res.json();
            if (res.ok) {
                setGeneratedKey(data.logos_key);
                onCreated(data as User);
            } else {
                setError(data.detail || "This username or email is already taken.");
            }
        } catch (err) {
            setError("Connection failed. Please try again.");
        } finally {
            setLoading(false);
        }
    };

    const handleCopy = async () => {
        if (Platform.OS === 'web') await navigator.clipboard.writeText(generatedKey);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };

    const closeAndReset = () => {
        setForm(EMPTY_FORM);
        setGeneratedKey("");
        setError("");
        onClose();
    };

    return (
        <BaseModal visible={visible} onClose={generatedKey ? () => {} : closeAndReset} maxWidth={380}>
            {!generatedKey ? (
                <VStack space="md">
                    <Text style={{ fontWeight: "700", fontSize: 18 }}>Create New User</Text>
                    <Input><InputField placeholder="First Name" value={form.prename} onChangeText={v => setForm(f => ({...f, prename: v}))} /></Input>
                    <Input><InputField placeholder="Last Name" value={form.name} onChangeText={v => setForm(f => ({...f, name: v}))} /></Input>
                    <Input><InputField placeholder="Username" value={form.username} autoCapitalize="none" onChangeText={v => setForm(f => ({...f, username: v}))} /></Input>
                    <Input><InputField placeholder="Email" value={form.email} autoCapitalize="none" onChangeText={v => setForm(f => ({...f, email: v}))} /></Input>
                    {error ? <Text style={{ color: "#e63535", fontSize: 12, fontWeight: "500" }}>{error}</Text> : null}
                    <HStack space="xs" className="flex-wrap mt-2">
                        {ALL_ROLES.map(role => (
                            <Pressable key={role} onPress={() => setForm(f => ({...f, role}))}
                                style={{ paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, borderWidth: 1, borderColor: form.role === role ? ROLE_COLORS[role] : "#eee" }}>
                                <Text style={{ fontSize: 11, fontWeight: "600", color: form.role === role ? ROLE_COLORS[role] : "#999" }}>{ROLE_LABELS[role]}</Text>
                            </Pressable>
                        ))}
                    </HStack>
                    <HStack space="md" className="justify-end mt-4">
                        <Button variant="outline" onPress={closeAndReset}><ButtonText>Cancel</ButtonText></Button>
                        <Button onPress={handleCreate} disabled={isAnyFieldEmpty || loading} style={{ opacity: (isAnyFieldEmpty || loading) ? 0.5 : 1 }}><ButtonText>Create</ButtonText></Button>
                    </HStack>
                </VStack>
            ) : (
                <VStack space="md">
                    <Text style={{ fontWeight: "700", fontSize: 18 }}>Success!</Text>
                    <Text style={{ fontSize: 14 }}>Copy the key now, it won't be shown again:</Text>
                    <Box className="bg-gray-100 p-3 rounded-lg border border-gray-200">
                        <ScrollView horizontal showsHorizontalScrollIndicator={false}><Text>{generatedKey}</Text></ScrollView>
                    </Box>
                    <HStack space="md" className="justify-end mt-2">
                        <Button variant="outline" onPress={handleCopy}><ButtonText>{copied ? "Copied!" : "Copy Key"}</ButtonText></Button>
                        <Button onPress={closeAndReset}><ButtonText>Done</ButtonText></Button>
                    </HStack>
                </VStack>
            )}
        </BaseModal>
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

function DeleteModal({ target, onClose, onConfirm }: any) {
    return (
        <BaseModal visible={!!target} onClose={onClose} maxWidth={400}>
            <Text style={{ fontWeight: "700", fontSize: 16, marginBottom: 8 }}>Delete User?</Text>
            <Text style={MODAL_STYLES.description}>{`Are you sure you want to remove ${target?.username}? This action is permanent.`}</Text>
            <HStack space="md" className="justify-end">
                <Button variant="outline" onPress={onClose}><ButtonText>Cancel</ButtonText></Button>
                <Button action="negative" onPress={onConfirm}><ButtonText>Delete</ButtonText></Button>
            </HStack>
        </BaseModal>
    );
}