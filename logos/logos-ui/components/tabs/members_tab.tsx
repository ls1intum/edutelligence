import React, { useState, useEffect } from "react";
import { ActivityIndicator, Pressable, ScrollView, View, TextInput } from "react-native";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Text } from "@/components/ui/text";
import { Box } from "@/components/ui/box";
import { Button, ButtonText } from "@/components/ui/button";
import { Input, InputField } from "@/components/ui/input";
import { Table, TableHeader, TableBody, TableHead, TableRow, TableData } from "@/components/ui/table";
import { Icon, TrashIcon, EditIcon } from "@/components/ui/icon";
import { ROLE_COLORS, ROLE_LABELS, API_BASE } from "@/components/statistics/constants";
import { UserRole } from "@/components/route-permissions";
import { ApiKeyModal } from "@/components/modals/api-key-modal";
import { BaseModal } from "@/components/modals/base-modal";

const formatMicroCentsToDollars = (microCents: number | null | undefined) => {
    if (microCents == null) return "";
    return (Number(microCents) / 100000000).toString();
};

const parseDollarsToMicroCents = (dollarsStr: string) => {
    const cleaned = dollarsStr.trim().replace(",", ".");
    if (!cleaned) return null;
    const parsed = parseFloat(cleaned);
    if (isNaN(parsed)) return null;
    return Math.round(parsed * 100000000);
};

const colStyles: Record<string, any> = {
    username: { width: "25%", minWidth: 120 },
    fullName: { width: "25%", minWidth: 140 },
    email:    { width: "30%", minWidth: 200 },
    keyInfo:  { width: "10%", minWidth: 100 },
    delete:  { width: 48, alignItems: "flex-end" },
};

export function Members_tab({ team, teamId, teamName, members, apiKeys, allUsers, adminUsers, isLogosAdmin, canEdit, canEditLimits, currentUserId, apiKey, onRefresh }: any) {
    const [selectedKey, setSelectedKey] = useState<any | null>(null);
    const [defaultBudget, setDefaultBudget] = useState(
        formatMicroCentsToDollars(team?.team_monthly_budget_micro_cents)
    );
    const [isSavingBudget, setIsSavingBudget] = useState(false);
    const [budgetSaveMessage, setBudgetSaveMessage] = useState("");

    useEffect(() => {
        if (team) {
            setDefaultBudget(formatMicroCentsToDollars(team.team_monthly_budget_micro_cents));
        }
    }, [team]);

    const handleSaveBudget = async () => {
        setIsSavingBudget(true);
        setBudgetSaveMessage("");
        try {
            const res = await fetch(`${API_BASE}/teams/${teamId}`, {
                method: "PATCH",
                headers: { "logos-key": apiKey, "Content-Type": "application/json" },
                body: JSON.stringify({
                    team_monthly_budget_micro_cents: parseDollarsToMicroCents(defaultBudget),
                }),
            });
            if (!res.ok) throw new Error();
            setBudgetSaveMessage("Saved!");
            if (onRefresh) onRefresh();
            setTimeout(() => setBudgetSaveMessage(""), 3000);
        } catch {
            alert("Error saving budget.");
        } finally {
            setIsSavingBudget(false);
        }
    };
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
      <VStack space="xl">
        <Box className="w-full overflow-hidden rounded-lg border border-outline-200 bg-secondary-200 p-3">
          <VStack space="xs">
            <HStack
              style={{ justifyContent: "space-between", alignItems: "center" }}
            >
              <Text
                style={{ fontWeight: "700", fontSize: 14, color: "#111827" }}
              >
                Monthly Team Budget (in $)
              </Text>
              {budgetSaveMessage ? (
                <Text style={{ fontSize: 12, color: "#16a34a" }}>
                  {budgetSaveMessage}
                </Text>
              ) : null}
            </HStack>

            <HStack space="md" style={{ alignItems: "center", marginTop: 4 }}>
              <Input
                variant="outline"
                size="md"
                isDisabled={!canEditLimits}
                style={{ backgroundColor: "#fff", flex: 1 }}
              >
                <InputField
                  value={defaultBudget}
                  onChangeText={setDefaultBudget}
                  keyboardType="decimal-pad"
                  placeholder="e.g. 150 (empty = unlimited)"
                  style={{ fontSize: 13 }}
                />
              </Input>

              {canEditLimits && (
                <Button
                  onPress={handleSaveBudget}
                  disabled={isSavingBudget}
                  variant="solid"
                  size="md"
                  style={{ minWidth: 100, height: "100%" }}
                >
                  {isSavingBudget ? (
                    <ActivityIndicator
                      color="#fff"
                      style={{ marginRight: 6 }}
                      size="small"
                    />
                  ) : null}
                  <ButtonText style={{ fontSize: 13 }}>
                    {isSavingBudget ? "Saving..." : "Save"}
                  </ButtonText>
                </Button>
              )}
            </HStack>
          </VStack>
        </Box>

        <VStack space="sm">
          <HStack
            style={{ justifyContent: "space-between", alignItems: "center" }}
          >
            <Text style={{ fontWeight: "700", fontSize: 16 }}>Owners</Text>
            {(isLogosAdmin || canEdit) && (
              <Button size="sm" onPress={() => setAddOwnerVisible(true)}>
                <ButtonText>+ Add Owner</ButtonText>
              </Button>
            )}
          </HStack>
          {owners.length === 0 ? (
            <Text style={{ color: "#9ca3af", fontSize: 13 }}>
              No owners assigned.
            </Text>
          ) : (
            <Box className="w-full overflow-hidden rounded-lg border border-outline-200 bg-secondary-200 p-2">
              <ScrollView horizontal contentContainerStyle={{ flexGrow: 1 }}>
                <Box className="min-w-full">
                  <Table className="w-full">
                    <TableHeader>
                      <TableRow className="bg-secondary-200">
                        <TableHead style={colStyles.username}>
                          Username
                        </TableHead>
                        <TableHead style={colStyles.fullName}>
                          Full Name
                        </TableHead>
                        <TableHead style={colStyles.email}>Email</TableHead>
                        <TableHead style={colStyles.keyInfo}>Key</TableHead>
                        <TableHead style={colStyles.delete}>{""}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {owners.map((owner: any) => (
                        <TableRow key={owner.id} className="bg-secondary-200">
                          <TableData style={colStyles.username}>
                            <Text style={{ fontWeight: "500" }}>
                              {owner.username}
                            </Text>
                          </TableData>
                          <TableData style={colStyles.fullName}>
                            <Text>
                              {owner.prename} {owner.name}
                            </Text>
                          </TableData>
                          <TableData style={colStyles.email}>
                            <Text style={{ fontSize: 12 }}>{owner.email}</Text>
                          </TableData>
                          <TableData style={colStyles.keyInfo}>
                            <KeyInfoCell userId={owner.id} />
                          </TableData>
                          <TableData style={colStyles.delete}>
                            {(isLogosAdmin || canEdit) &&
                              owner.id !== currentUserId && (
                                <Pressable
                                  onPress={() => handleRemoveOwner(owner.id)}
                                  style={{ padding: 8 }}
                                >
                                  <Icon
                                    as={TrashIcon}
                                    size="sm"
                                    className="text-typography-400"
                                  />
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
          <HStack
            style={{ justifyContent: "space-between", alignItems: "center" }}
          >
            <Text style={{ fontWeight: "700", fontSize: 16 }}>Members</Text>
            {canEdit && (
              <Button size="sm" onPress={() => setAddMemberVisible(true)}>
                <ButtonText>+ Add Member</ButtonText>
              </Button>
            )}
          </HStack>
          {regularMembers.length === 0 ? (
            <Text style={{ color: "#9ca3af", fontSize: 13 }}>
              No members yet.
            </Text>
          ) : (
            <Box className="w-full overflow-hidden rounded-lg border border-outline-200 bg-secondary-200 p-2">
              <ScrollView horizontal contentContainerStyle={{ flexGrow: 1 }}>
                <Box className="min-w-full">
                  <Table className="w-full">
                    <TableHeader>
                      <TableRow className="bg-secondary-200">
                        <TableHead style={colStyles.username}>
                          Username
                        </TableHead>
                        <TableHead style={colStyles.fullName}>
                          Full Name
                        </TableHead>
                        <TableHead style={colStyles.email}>Email</TableHead>
                        <TableHead style={colStyles.keyInfo}>Key</TableHead>
                        <TableHead style={colStyles.delete}>{""}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {regularMembers.map((member: any) => (
                        <TableRow key={member.id} className="bg-secondary-200">
                          <TableData style={colStyles.username}>
                            <Text style={{ fontWeight: "500" }}>
                              {member.username}
                            </Text>
                          </TableData>
                          <TableData style={colStyles.fullName}>
                            <Text>
                              {member.prename} {member.name}
                            </Text>
                          </TableData>
                          <TableData style={colStyles.email}>
                            <Text style={{ fontSize: 12 }}>{member.email}</Text>
                          </TableData>
                          <TableData style={colStyles.keyInfo}>
                            <KeyInfoCell userId={member.id} />
                          </TableData>
                          <TableData style={colStyles.delete}>
                            {canEdit && member.id !== currentUserId && (
                              <Pressable
                                onPress={() => handleRemoveMember(member.id)}
                                style={{ padding: 8 }}
                              >
                                <Icon
                                  as={TrashIcon}
                                  size="sm"
                                  className="text-typography-400"
                                />
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
          canEdit={isLogosAdmin || canEdit}
          onSaved={onRefresh}
        />
        <BaseModal
          visible={addOwnerVisible}
          onClose={() => {
            setAddOwnerVisible(false);
            setOwnerSearch("");
          }}
          maxWidth={1000}
        >
          <VStack space="md">
            <Text style={{ fontWeight: "700", fontSize: 18 }}>Add Owner</Text>
            <View
              style={{
                borderWidth: 1,
                borderColor: "#e2e8f0",
                borderRadius: 8,
                paddingHorizontal: 10,
                paddingVertical: 9,
              }}
            >
              <TextInput
                placeholder="Search admin users..."
                value={ownerSearch}
                onChangeText={setOwnerSearch}
                autoFocus
                style={
                  { fontSize: 13, color: "#333", outlineStyle: "none" } as any
                }
                placeholderTextColor="#aaa"
              />
            </View>
            <ScrollView
              style={{ maxHeight: 240 }}
              keyboardShouldPersistTaps="handled"
            >
              {filteredForOwner.map((user: any) => (
                <Pressable
                  key={user.id}
                  onPress={() => handleAddOwner(user.id)}
                  style={{
                    paddingHorizontal: 10,
                    paddingVertical: 6,
                    borderBottomWidth: 1,
                    borderBottomColor: "#f3f4f6",
                  }}
                >
                  <Text style={{ fontWeight: "500", fontSize: 13 }}>
                    {user.username}
                  </Text>
                  <Text style={{ fontSize: 12, color: "#6b7280" }}>
                    {user.prename} {user.name}
                  </Text>
                </Pressable>
              ))}
              {filteredForOwner.length === 0 && (
                <Text
                  style={{
                    paddingHorizontal: 10,
                    paddingVertical: 6,
                    color: "#9ca3af",
                    fontSize: 13,
                  }}
                >
                  No admin users available.
                </Text>
              )}
            </ScrollView>
            <HStack space="md" className="justify-end">
              <Button
                variant="outline"
                onPress={() => {
                  setAddOwnerVisible(false);
                  setOwnerSearch("");
                }}
              >
                <ButtonText>Cancel</ButtonText>
              </Button>
            </HStack>
          </VStack>
        </BaseModal>

        <BaseModal
          visible={addMemberVisible}
          onClose={() => {
            setAddMemberVisible(false);
            setMemberSearch("");
          }}
          maxWidth={1000}
        >
          <VStack space="md">
            <Text style={{ fontWeight: "700", fontSize: 18 }}>Add Member</Text>
            <View
              style={{
                borderWidth: 1,
                borderColor: "#e2e8f0",
                borderRadius: 8,
                paddingHorizontal: 10,
                paddingVertical: 9,
              }}
            >
              <TextInput
                placeholder="Search users..."
                value={memberSearch}
                onChangeText={setMemberSearch}
                autoFocus
                style={
                  { fontSize: 13, color: "#333", outlineStyle: "none" } as any
                }
                placeholderTextColor="#aaa"
              />
            </View>
            <ScrollView
              style={{ maxHeight: 240 }}
              keyboardShouldPersistTaps="handled"
            >
              {filteredForMember.map((user: any) => (
                <Pressable
                  key={user.id}
                  onPress={() => handleAddMember(user.id)}
                  style={{
                    paddingHorizontal: 10,
                    paddingVertical: 6,
                    borderBottomWidth: 1,
                    borderBottomColor: "#f3f4f6",
                  }}
                >
                  <Text style={{ fontWeight: "500", fontSize: 13 }}>
                    {user.username}
                  </Text>
                  <Text style={{ fontSize: 12, color: "#6b7280" }}>
                    {user.prename} {user.name}
                  </Text>
                </Pressable>
              ))}
              {filteredForMember.length === 0 && (
                <Text
                  style={{
                    paddingHorizontal: 10,
                    paddingVertical: 6,
                    color: "#9ca3af",
                    fontSize: 13,
                  }}
                >
                  No users to add.
                </Text>
              )}
            </ScrollView>
            <HStack space="md" className="justify-end">
              <Button
                variant="outline"
                onPress={() => {
                  setAddMemberVisible(false);
                  setMemberSearch("");
                }}
              >
                <ButtonText>Cancel</ButtonText>
              </Button>
            </HStack>
          </VStack>
        </BaseModal>
      </VStack>
    );
}
