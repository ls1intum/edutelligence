import React, { useState } from "react";
import { Pressable, ScrollView, View, TextInput } from "react-native";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Text } from "@/components/ui/text";
import { Box } from "@/components/ui/box";
import { Button, ButtonText } from "@/components/ui/button";
import { Table, TableHeader, TableBody, TableHead, TableRow, TableData } from "@/components/ui/table";
import { Icon, TrashIcon, EditIcon } from "@/components/ui/icon";
import { ROLE_COLORS, ROLE_LABELS, API_BASE } from "@/components/statistics/constants";
import { UserRole } from "@/components/route-permissions";
import { ApiKeyModal } from "@/components/modals/api-key-modal";
import { BaseModal } from "@/components/modals/base-modal";

const colStyles: Record<string, any> = {
    username: { width: "20%", minWidth: 120 },
    fullName: { width: "20%", minWidth: 140 },
    email:    { width: "25%", minWidth: 200 },
    role:     { width: "20%", minWidth: 150 },
    keyInfo:  { width: "5%", minWidth: 100 },
    delete:  { width: 48, alignItems: "flex-end" },
};

export function Members_tab({ team, teamId, teamName, members, apiKeys, allUsers, adminUsers, isLogosAdmin, canEdit, currentUserId, apiKey, onRefresh }: any) {    const [selectedKey, setSelectedKey] = useState<any | null>(null);
    const [addOwnerVisible, setAddOwnerVisible] = useState(false);
    const [ownerSearch, setOwnerSearch] = useState("");
    const [addMemberVisible, setAddMemberVisible] = useState(false);
    const [memberSearch, setMemberSearch] = useState("");

    const owners = members.filter((m: any) => m.is_owner);
    const regularMembers = members.filter((m: any) => !m.is_owner);
    const memberIds = new Set(members.map((m: any) => m.id));
    const ownerIds = new Set(owners.map((o: any) => o.id));

    const handleAddOwner = async (userId: number) => {
        setAddOwnerVisible(false);
        setOwnerSearch("");
        try {
            await fetch(`${API_BASE}/teams/${teamId}/members`, {
                method: "POST",
                headers: { "logos-key": apiKey, "Content-Type": "application/json" },
                body: JSON.stringify({ user_id: userId, is_owner: true }),
            });
            onRefresh();
        } catch (e) {}
    };

    const handleRemoveOwner = async (userId: number) => {
        try {
            await fetch(`${API_BASE}/teams/${teamId}/members/${userId}`, {
                method: "DELETE",
                headers: { "logos-key": apiKey },
            });
            onRefresh();
        } catch (e) {}
    };

    const handleAddMember = async (userId: number) => {
        setAddMemberVisible(false);
        setMemberSearch("");
        try {
            await fetch(`${API_BASE}/teams/${teamId}/members`, {
                method: "POST",
                headers: { "logos-key": apiKey, "Content-Type": "application/json" },
                body: JSON.stringify({ user_id: userId }),
            });
            onRefresh();
        } catch (e) {}
    };

    const handleRemoveMember = async (userId: number) => {
        try {
            await fetch(`${API_BASE}/teams/${teamId}/members/${userId}`, {
                method: "DELETE",
                headers: { "logos-key": apiKey },
            });
            onRefresh();
        } catch (e) {}
    };

    const availableForOwner = adminUsers
        ?.filter((u: any) => !ownerIds.has(u.id))
        .map((u: any) => {
            const full = allUsers?.find((au: any) => au.id === u.id);
            return { ...u, prename: full?.prename ?? "", name: full?.name ?? "" };
        }) || [];
    const ownerTerms = ownerSearch.toLowerCase().trim().split(/\s+/);
    const filteredForOwner = ownerSearch.trim()
        ? availableForOwner.filter((u: any) => {
            const searchableText = `${u.username} ${u.prename} ${u.name}`.toLowerCase();
            return ownerTerms.every(term => searchableText.includes(term));
        })
        : availableForOwner;

    const availableForMember = allUsers?.filter((u: any) => !memberIds.has(u.id)) || [];
    const memberTerms = memberSearch.toLowerCase().trim().split(/\s+/);
    const filteredForMember = memberSearch.trim()
        ? availableForMember.filter((u: any) => {
            const searchableText = `${u.username} ${u.prename} ${u.name}`.toLowerCase();
            return memberTerms.every(term => searchableText.includes(term));
        })
        : availableForMember;

    const KeyInfoCell = ({ userId }: { userId: number }) => {
        const userKey = apiKeys.find((k: any) => k.user_id === userId);

        if (!userKey) return <Text style={{ color: "#9ca3af", fontSize: 12 }}>No Key</Text>;

        return (
            <Pressable
                onPress={() => setSelectedKey(userKey)}
                style={{
                    flexDirection: "row",
                    alignItems: "center",
                    alignSelf: "center"
                }}
            >
                <Icon as={EditIcon} size="sm" />
            </Pressable>
        );
    };

    return (
        <VStack space="xl" style={{ marginTop: 16, paddingBottom: 40 }}>
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
                                            <TableHead style={colStyles.username}>Username</TableHead>
                                            <TableHead style={colStyles.fullName}>Full Name</TableHead>
                                            <TableHead style={colStyles.email}>Email</TableHead>
                                            <TableHead style={colStyles.role}>Role</TableHead>
                                            <TableHead style={colStyles.keyInfo}>Key</TableHead>
                                            <TableHead style={colStyles.delete}>{""}</TableHead>
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {owners.map((owner: any) => (
                                            <TableRow key={owner.id} className="bg-secondary-200">
                                                <TableData style={colStyles.username}>
                                                    <Text style={{ fontWeight: "500" }}>{owner.username}</Text>
                                                </TableData>
                                                <TableData style={colStyles.fullName}>
                                                    <Text>{owner.prename} {owner.name}</Text>
                                                </TableData>
                                                <TableData style={colStyles.email}>
                                                    <Text style={{ fontSize: 12 }}>{owner.email}</Text>
                                                </TableData>
                                                <TableData style={colStyles.role}>
                                                    <View style={{ borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4, borderWidth: 1, borderColor: ROLE_COLORS[owner.role as UserRole], alignSelf: "flex-start" }}>
                                                        <Text style={{ color: ROLE_COLORS[owner.role as UserRole], fontWeight: "600", fontSize: 11 }}>{ROLE_LABELS[owner.role as UserRole]}</Text>
                                                    </View>
                                                </TableData>
                                                <TableData style={colStyles.keyInfo}>
                                                    <KeyInfoCell userId={owner.id} />
                                                </TableData>
                                                <TableData style={colStyles.delete}>
                                                    {isLogosAdmin && owner.id !== currentUserId && (
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
                    {canEdit && (
                        <Button size="sm" onPress={() => setAddMemberVisible(true)}>
                            <ButtonText>+ Add Member</ButtonText>
                        </Button>
                    )}
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
                                            <TableHead style={colStyles.username}>Username</TableHead>
                                            <TableHead style={colStyles.fullName}>Full Name</TableHead>
                                            <TableHead style={colStyles.email}>Email</TableHead>
                                            <TableHead style={colStyles.role}>Role</TableHead>
                                            <TableHead style={colStyles.keyInfo}>Key</TableHead>
                                            <TableHead style={colStyles.delete}>{""}</TableHead>
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {regularMembers.map((member: any) => (
                                            <TableRow key={member.id} className="bg-secondary-200">
                                                <TableData style={colStyles.username}>
                                                    <Text style={{ fontWeight: "500" }}>{member.username}</Text>
                                                </TableData>
                                                <TableData style={colStyles.fullName}>
                                                    <Text>{member.prename} {member.name}</Text>
                                                </TableData>
                                                <TableData style={colStyles.email}>
                                                    <Text style={{ fontSize: 12 }}>{member.email}</Text>
                                                </TableData>
                                                <TableData style={colStyles.role}>
                                                    <View style={{ borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4, borderWidth: 1, borderColor: ROLE_COLORS[member.role as UserRole], alignSelf: "flex-start" }}>
                                                        <Text style={{ color: ROLE_COLORS[member.role as UserRole], fontWeight: "600", fontSize: 11 }}>{ROLE_LABELS[member.role as UserRole]}</Text>
                                                    </View>
                                                </TableData>
                                                <TableData style={colStyles.keyInfo}>
                                                    <KeyInfoCell userId={member.id} />
                                                </TableData>
                                                <TableData style={colStyles.delete}>
                                                    {canEdit && member.id !== currentUserId && (
                                                        <Pressable onPress={() => handleRemoveMember(member.id)} style={{ padding: 8 }}>
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

            <ApiKeyModal
                visible={!!selectedKey}
                onClose={() => setSelectedKey(null)}
                apiKeyData={selectedKey}
                team={team}
                canEdit={isLogosAdmin}
                onSaved={onRefresh}
            />
            <BaseModal visible={addOwnerVisible} onClose={() => { setAddOwnerVisible(false); setOwnerSearch(""); }} maxWidth={1000}>
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
                        {filteredForOwner.map((user: any) => (
                            <Pressable key={user.id} onPress={() => handleAddOwner(user.id)}
                                style={{ paddingHorizontal: 10, paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: "#f3f4f6" }}>
                                <Text style={{ fontWeight: "500", fontSize: 13 }}>{user.username}</Text>
                                <Text style={{ fontSize: 12, color: "#6b7280" }}>{user.prename} {user.name}</Text>
                            </Pressable>
                        ))}
                        {filteredForOwner.length === 0 && (
                            <Text style={{ paddingHorizontal: 10, paddingVertical: 6, color: "#9ca3af", fontSize: 13 }}>No admin users available.</Text>
                        )}
                    </ScrollView>
                    <HStack space="md" className="justify-end">
                        <Button variant="outline" onPress={() => { setAddOwnerVisible(false); setOwnerSearch(""); }}><ButtonText>Cancel</ButtonText></Button>
                    </HStack>
                </VStack>
            </BaseModal>

            <BaseModal visible={addMemberVisible} onClose={() => { setAddMemberVisible(false); setMemberSearch(""); }} maxWidth={1000}>
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
                        {filteredForMember.map((user: any) => (
                            <Pressable key={user.id} onPress={() => handleAddMember(user.id)}
                                style={{ paddingHorizontal: 10, paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: "#f3f4f6" }}>
                                <Text style={{ fontWeight: "500", fontSize: 13 }}>{user.username}</Text>
                                <Text style={{ fontSize: 12, color: "#6b7280" }}>{user.prename} {user.name}</Text>
                            </Pressable>
                        ))}
                        {filteredForMember.length === 0 && (
                            <Text style={{ paddingHorizontal: 10, paddingVertical: 6, color: "#9ca3af", fontSize: 13 }}>No users to add.</Text>
                        )}
                    </ScrollView>
                    <HStack space="md" className="justify-end">
                        <Button variant="outline" onPress={() => { setAddMemberVisible(false); setMemberSearch(""); }}><ButtonText>Cancel</ButtonText></Button>
                    </HStack>
                </VStack>
            </BaseModal>
        </VStack>
    );
}