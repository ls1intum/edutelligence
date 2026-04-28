import React, { useState, useEffect, useCallback } from "react";
import { Pressable, ScrollView, View, ActivityIndicator, TextInput } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useAuth } from "@/components/auth-shell";
import { API_BASE, ROLE_COLORS, ROLE_LABELS, User } from "@/components/statistics/constants";
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Button, ButtonText } from "@/components/ui/button";
import { Table, TableHeader, TableBody, TableHead, TableRow, TableData } from "@/components/ui/table";
import { Icon, TrashIcon, ArrowLeftIcon } from "@/components/ui/icon";
import { UserRole } from "@/components/route-permissions";
import { BaseModal } from "@/components/modals/base-modal";
import { ConfirmDeleteModal } from "@/components/modals/confirm-delete-modal";
import { CreateUserModal } from "@/components/modals/create-user-modal";

type Member = {
    id: number;
    username: string;
    prename: string;
    name: string;
    email: string;
    role: UserRole;
    is_owner: boolean;
};

export default function TeamDetail() {
    const { id } = useLocalSearchParams<{ id: string }>();
    const { apiKey, role } = useAuth();
    const router = useRouter();
    const isLogosAdmin = role === "logos_admin";

    const [teamName, setTeamName] = useState("");
    const [members, setMembers] = useState<Member[]>([]);
    const [allUsers, setAllUsers] = useState<User[]>([]);
    const [adminUsers, setAdminUsers] = useState<User[]>([]);
    const [loading, setLoading] = useState(true);
    const [addMemberVisible, setAddMemberVisible] = useState(false);
    const [addOwnerVisible, setAddOwnerVisible] = useState(false);
    const [deleteVisible, setDeleteVisible] = useState(false);
    const [createVisible, setCreateVisible] = useState(false);
    const [memberSearch, setMemberSearch] = useState("");
    const [ownerSearch, setOwnerSearch] = useState("");

    const owners = members.filter(m => m.is_owner);
    const regularMembers = members.filter(m => !m.is_owner);
    const memberIds = new Set(members.map(m => m.id));
    const ownerIds = new Set(owners.map(o => o.id));

    const availableForMember = allUsers.filter(u => !memberIds.has(u.id));
    const filteredForMember = memberSearch.trim()
        ? availableForMember.filter(u =>
            u.username.toLowerCase().includes(memberSearch.toLowerCase()) ||
            u.prename.toLowerCase().includes(memberSearch.toLowerCase()))
        : availableForMember;
    const showCreateNew = memberSearch.trim().length > 0 && filteredForMember.length === 0;

    const availableForOwner = adminUsers
        .filter(u => !ownerIds.has(u.id))
        .map(u => {
            const full = allUsers.find(au => au.id === u.id);
            return { ...u, prename: full?.prename ?? "", name: full?.name ?? "" };
        });
    const filteredForOwner = ownerSearch.trim()
        ? availableForOwner.filter(u =>
            u.username.toLowerCase().includes(ownerSearch.toLowerCase()) ||
            u.prename.toLowerCase().includes(ownerSearch.toLowerCase()) ||
            u.name.toLowerCase().includes(ownerSearch.toLowerCase()))
        : availableForOwner;

    const fetchDetail = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/teams/${id}/members`, {
                headers: { "logos-key": apiKey },
            });
            if (!res.ok) {
                router.replace("/team-management");
                return;
            }
            const data = await res.json();
            setTeamName(data.team.name);
            setMembers(data.members);
        } catch {
            router.replace("/team-management");
        } finally {
            setLoading(false);
        }
    }, [id, apiKey]);

    useEffect(() => {
        fetchDetail();
        fetch(`${API_BASE}/users`, { headers: { "logos-key": apiKey } })
            .then(r => r.ok ? r.json() : [])
            .then(setAllUsers)
            .catch(() => setAllUsers([]));
        if (isLogosAdmin) {
            fetch(`${API_BASE}/users/admins`, { headers: { "logos-key": apiKey } })
                .then(r => r.ok ? r.json() : [])
                .then(setAdminUsers)
                .catch(() => setAdminUsers([]));
        }
    }, [fetchDetail, apiKey, isLogosAdmin]);

    const handleAddOwner = async (userId: number) => {
        setAddOwnerVisible(false);
        setOwnerSearch("");
        try {
            const res = await fetch(`${API_BASE}/teams/${id}/members`, {
                method: "POST",
                headers: { "logos-key": apiKey, "Content-Type": "application/json" },
                body: JSON.stringify({ user_id: userId, is_owner: true }),
            });
            if (res.ok) fetchDetail();
        } catch {
            fetchDetail();
        }
    };

    const handleRemoveOwner = async (userId: number) => {
        setMembers(prev => prev.map(m => m.id === userId ? { ...m, is_owner: false } : m));
        try {
            const res = await fetch(`${API_BASE}/teams/${id}/members/${userId}`, {
                method: "PATCH",
                headers: { "logos-key": apiKey, "Content-Type": "application/json" },
                body: JSON.stringify({ is_owner: false }),
            });
            if (!res.ok) fetchDetail();
        } catch {
            fetchDetail();
        }
    };

    const handleAddMember = async (userId: number) => {
        setAddMemberVisible(false);
        setMemberSearch("");
        try {
            const res = await fetch(`${API_BASE}/teams/${id}/members`, {
                method: "POST",
                headers: { "logos-key": apiKey, "Content-Type": "application/json" },
                body: JSON.stringify({ user_id: userId }),
            });
            if (res.ok) fetchDetail();
        } catch {
            fetchDetail();
        }
    };

    const handleRemoveMember = async (userId: number) => {
        setMembers(prev => prev.filter(m => m.id !== userId));
        try {
            await fetch(`${API_BASE}/teams/${id}/members/${userId}`, {
                method: "DELETE",
                headers: { "logos-key": apiKey },
            });
        } catch {
            fetchDetail();
        }
    };

    const handleDeleteTeam = async () => {
        setDeleteVisible(false);
        try {
            await fetch(`${API_BASE}/teams/${id}`, {
                method: "DELETE",
                headers: { "logos-key": apiKey },
            });
            router.replace("/team-management");
        } catch {
            // nothing
        }
    };

    if (loading) {
        return (
            <VStack className="items-center justify-center p-8" space="lg">
                <ActivityIndicator size="large" color="#006DFF" />
                <Text className="text-gray-500">Loading team...</Text>
            </VStack>
        );
    }

    return (
        <VStack className="w-full" space="xl">
            <HStack style={{ alignItems: "center" }}>
                <Pressable onPress={() => router.push("/team-management")} style={{ padding: 4, width: 32 }}>
                    <Icon as={ArrowLeftIcon} size="md" className="text-typography-600" />
                </Pressable>
                <Text size="2xl" className="font-bold text-black dark:text-white"
                    style={{ flex: 1, textAlign: "center" }}>
                    {teamName}
                </Text>
                <View style={{ width: 32 }} />
            </HStack>
            <VStack space="sm">
                <HStack style={{ justifyContent: "space-between", alignItems: "center" }}>
                    <Text style={{ fontWeight: "700", fontSize: 16 }}>Owners</Text>
                    {isLogosAdmin && (
                        <Button size="sm" onPress={() => setAddOwnerVisible(true)}>
                            <ButtonText>+ Add Owner</ButtonText>
                        </Button>
                    )}
                </HStack>
                {owners.length === 0 ? (
                    <Text style={{ color: "#9ca3af", fontSize: 13 }}>No owners assigned.</Text>
                ) : (
                    <Box className="w-full overflow-hidden rounded-lg border border-outline-200 bg-secondary-200 p-2">
                        <ScrollView horizontal contentContainerStyle={{ flexGrow: 1 }}>
                            <Box className="min-w-full">
                                <Table className="w-full">
                                    <TableHeader>
                                        <TableRow className="bg-secondary-200">
                                            <TableHead>Username</TableHead>
                                            <TableHead>Full Name</TableHead>
                                            <TableHead>Email</TableHead>
                                            <TableHead>Role</TableHead>
                                            <TableHead>{""}</TableHead>
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {owners.map(owner => (
                                            <TableRow key={owner.id} className="bg-secondary-200">
                                                <TableData>
                                                    <Text>{owner.username}</Text>
                                                </TableData>
                                                <TableData>
                                                    <Text style={{ fontWeight: "500" }}>{owner.prename} {owner.name}</Text>
                                                </TableData>
                                                <TableData>
                                                    <Text style={{ fontSize: 12 }}>{owner.email}</Text>
                                                </TableData>
                                                <TableData>
                                                    <View style={{
                                                        borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4,
                                                        borderWidth: 1, borderColor: ROLE_COLORS[owner.role],
                                                    }}>
                                                        <Text style={{ color: ROLE_COLORS[owner.role], fontWeight: "600", fontSize: 12 }}>
                                                            {ROLE_LABELS[owner.role]}
                                                        </Text>
                                                    </View>
                                                </TableData>
                                                <TableData style={{ width: 48, alignItems: "flex-end" }}>
                                                    {isLogosAdmin && (
                                                        <Pressable onPress={() => handleRemoveOwner(owner.id)} style={{ padding: 8 }}>
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

            <VStack space="sm">
                <HStack style={{ justifyContent: "space-between", alignItems: "center" }}>
                    <Text style={{ fontWeight: "700", fontSize: 16 }}>Members</Text>
                    <Button size="sm" onPress={() => setAddMemberVisible(true)}>
                        <ButtonText>+ Add Member</ButtonText>
                    </Button>
                </HStack>
                {regularMembers.length === 0 ? (
                    <Text style={{ color: "#9ca3af", fontSize: 13 }}>No members yet.</Text>
                ) : (
                    <Box className="w-full overflow-hidden rounded-lg border border-outline-200 bg-secondary-200 p-2">
                        <ScrollView horizontal contentContainerStyle={{ flexGrow: 1 }}>
                            <Box className="min-w-full">
                                <Table className="w-full">
                                    <TableHeader>
                                        <TableRow className="bg-secondary-200">
                                            <TableHead>Username</TableHead>
                                            <TableHead>Full Name</TableHead>
                                            <TableHead>Email</TableHead>
                                            <TableHead>Role</TableHead>
                                            <TableHead>{""}</TableHead>
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {regularMembers.map(member => (
                                            <TableRow key={member.id} className="bg-secondary-200">
                                                <TableData>
                                                    <Text>{member.username}</Text>
                                                </TableData>
                                                <TableData>
                                                    <Text style={{ fontWeight: "500" }}>{member.prename} {member.name}</Text>
                                                </TableData>
                                                <TableData>
                                                    <Text style={{ fontSize: 12 }}>{member.email}</Text>
                                                </TableData>
                                                <TableData>
                                                    <View style={{
                                                        borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4,
                                                        borderWidth: 1, borderColor: ROLE_COLORS[member.role],
                                                    }}>
                                                        <Text style={{ color: ROLE_COLORS[member.role], fontWeight: "600", fontSize: 12 }}>
                                                            {ROLE_LABELS[member.role]}
                                                        </Text>
                                                    </View>
                                                </TableData>
                                                <TableData style={{ width: 48, alignItems: "flex-end" }}>
                                                    <Pressable onPress={() => handleRemoveMember(member.id)} style={{ padding: 8 }}>
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
            </VStack>

            <VStack space="sm">
                <Text style={{ fontWeight: "700", fontSize: 16, color: "#9ca3af" }}>
                    Configuration
                </Text>
                <HStack space="md">
                    <Box style={{
                        flex: 1, padding: 16, borderRadius: 8,
                        borderWidth: 1, borderColor: "#ccc", borderStyle: "dashed",
                    }}>
                        <Text style={{ fontWeight: "600", color: "#ccc" }}>Rate Limit</Text>
                        <Text style={{ fontSize: 12, color: "#ccc", marginTop: 4 }}>Coming soon</Text>
                    </Box>
                    <Box style={{
                        flex: 1, padding: 16, borderRadius: 8,
                        borderWidth: 1, borderColor: "#ccc", borderStyle: "dashed",
                    }}>
                        <Text style={{ fontWeight: "600", color: "#ccc" }}>Models & Providers</Text>
                        <Text style={{ fontSize: 12, color: "#ccc", marginTop: 4 }}>Coming soon</Text>
                    </Box>
                </HStack>
            </VStack>
            <Button action="negative" onPress={() => setDeleteVisible(true)} style={{ alignSelf: "center" }}>
                <ButtonText>Delete Team</ButtonText>
            </Button>
            <BaseModal
                visible={addOwnerVisible}
                onClose={() => { setAddOwnerVisible(false); setOwnerSearch(""); }}
                maxWidth={400}
            >
                <VStack space="md">
                    <Text style={{ fontWeight: "700", fontSize: 18 }}>Add Owner</Text>
                    <View style={{ borderWidth: 1, borderColor: "#e2e8f0", borderRadius: 8, paddingHorizontal: 10, paddingVertical: 9 }}>
                        <TextInput
                            placeholder="Search admin users..."
                            value={ownerSearch}
                            onChangeText={setOwnerSearch}
                            autoFocus
                            style={{ fontSize: 13, color: "#333", outlineStyle: "none" } as any}
                            placeholderTextColor="#aaa"
                        />
                    </View>
                    <ScrollView style={{ maxHeight: 240 }} keyboardShouldPersistTaps="handled">
                        {filteredForOwner.map(user => (
                            <Pressable key={user.id} onPress={() => handleAddOwner(user.id)}
                                style={{ paddingHorizontal: 10, paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: "#f3f4f6" }}>
                                <Text style={{ fontWeight: "500", fontSize: 13 }}>{user.username}</Text>
                                <Text style={{ fontSize: 12, color: "#6b7280" }}>{user.prename} {user.name}</Text>
                            </Pressable>
                        ))}
                        {filteredForOwner.length === 0 && (
                            <Text style={{ paddingHorizontal: 10, paddingVertical: 6, color: "#9ca3af", fontSize: 13 }}>
                                No admin users available.
                            </Text>
                        )}
                    </ScrollView>
                    <HStack space="md" className="justify-end">
                        <Button variant="outline" onPress={() => { setAddOwnerVisible(false); setOwnerSearch(""); }}>
                            <ButtonText>Cancel</ButtonText>
                        </Button>
                    </HStack>
                </VStack>
            </BaseModal>
            <BaseModal
                visible={addMemberVisible}
                onClose={() => { setAddMemberVisible(false); setMemberSearch(""); }}
                maxWidth={400}
            >
                <VStack space="md">
                    <Text style={{ fontWeight: "700", fontSize: 18 }}>Add Member</Text>
                    <View style={{ borderWidth: 1, borderColor: "#e2e8f0", borderRadius: 8, paddingHorizontal: 10, paddingVertical: 9 }}>
                        <TextInput
                            placeholder="Search users..."
                            value={memberSearch}
                            onChangeText={setMemberSearch}
                            autoFocus
                            style={{ fontSize: 13, color: "#333", outlineStyle: "none" } as any}
                            placeholderTextColor="#aaa"
                        />
                    </View>
                    <ScrollView style={{ maxHeight: 240 }} keyboardShouldPersistTaps="handled">
                        {filteredForMember.map(user => (
                            <Pressable key={user.id} onPress={() => handleAddMember(user.id)}
                                style={{ paddingHorizontal: 10, paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: "#f3f4f6" }}>
                                <Text style={{ fontWeight: "500", fontSize: 13 }}>{user.username}</Text>
                                <Text style={{ fontSize: 12, color: "#6b7280" }}>{user.prename} {user.name}</Text>
                            </Pressable>
                        ))}
                        {showCreateNew && (
                            <Pressable
                                onPress={() => { setAddMemberVisible(false); setMemberSearch(""); setCreateVisible(true); }}
                                style={{ paddingHorizontal: 10, paddingVertical: 6 }}>
                                <Text style={{ color: "#006DFF", fontWeight: "600", fontSize: 13 }}>
                                    + Create new user "{memberSearch}"
                                </Text>
                            </Pressable>
                        )}
                        {!showCreateNew && filteredForMember.length === 0 && (
                            <Text style={{ paddingHorizontal: 10, paddingVertical: 6, color: "#9ca3af", fontSize: 13 }}>No users to add.</Text>
                        )}
                    </ScrollView>
                    <HStack space="md" className="justify-end">
                        <Button variant="outline" onPress={() => { setAddMemberVisible(false); setMemberSearch(""); }}>
                            <ButtonText>Cancel</ButtonText>
                        </Button>
                    </HStack>
                </VStack>
            </BaseModal>
            <ConfirmDeleteModal
                visible={deleteVisible}
                onClose={() => setDeleteVisible(false)}
                onConfirm={handleDeleteTeam}
                title="Delete Team?"
                message={`Are you sure you want to delete "${teamName}"? This action is permanent.`}
            />

            <CreateUserModal
                visible={createVisible}
                onClose={() => setCreateVisible(false)}
                onCreated={() => { fetchDetail(); setCreateVisible(false); }}
                apiKey={apiKey}
                showRoleSelector={isLogosAdmin}
                showTeamPicker={false}
                preselectedTeamIds={[Number(id)]}
            />
        </VStack>
    );
}