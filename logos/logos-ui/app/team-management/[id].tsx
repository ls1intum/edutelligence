import React, { useState, useEffect, useCallback } from "react";
import { Pressable, View, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useAuth } from "@/components/auth-shell";
import { API_BASE, User } from "@/components/statistics/constants";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Icon, ArrowLeftIcon, EditIcon } from "@/components/ui/icon";
import { ConfirmDeleteModal } from "@/components/modals/confirm-delete-modal";
import { BaseModal } from "@/components/modals/base-modal";
import { Input, InputField } from "@/components/ui/input";
import { Button, ButtonText } from "@/components/ui/button";

import { Overview_tab } from "@/components/tabs/overview_tab";
import { Members_tab } from "@/components/tabs/members_tab";
import { Application_keys_tab } from "../../components/tabs/application_keys_tab";
import { Models_tab } from "@/components/tabs/models_tab";
import { Settings_tab } from "@/components/tabs/settings_tab";

type Tab = "overview" | "members" | "application_keys" | "models" | "settings";

export default function TeamDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const teamId = Number(id);
  const { apiKey, role, userId: currentUserId } = useAuth();
  const router = useRouter();
  const isLogosAdmin = role === "logos_admin";

  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [team, setTeam] = useState<any>(null);
  const [teamName, setTeamName] = useState("");
  const [members, setMembers] = useState<any[]>([]);
  const [apiKeys, setApiKeys] = useState<any[]>([]);
  const [allUsers, setAllUsers] = useState<User[]>([]);
  const [teamModelsCount, setTeamModelsCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [isOwner, setIsOwner] = useState(false);
  const [deleteVisible, setDeleteVisible] = useState(false);
  const [adminUsers, setAdminUsers] = useState<User[]>([]);

  const [editNameVisible, setEditNameVisible] = useState(false);
  const [editNameInput, setEditNameInput] = useState("");
  const [editNameLoading, setEditNameLoading] = useState(false);
  const [editNameError, setEditNameError] = useState("");

  const fetchAllData = useCallback(async () => {
    setLoading(true);
    try {
      const memberRes = await fetch(`${API_BASE}/teams/${teamId}/members`, {
        headers: { "logos-key": apiKey },
      });
      if (!memberRes.ok) throw new Error();
      const memberData = await memberRes.json();

      setTeam(memberData.team);
      setTeamName(memberData.team.name);
      setMembers(memberData.members);
      const ownerFlag = isLogosAdmin || !!memberData.team.is_caller_owner;
      setIsOwner(ownerFlag);

      const keysRes = await fetch(
        `${API_BASE}/admin/teams/${teamId}/api-keys`,
        { headers: { "logos-key": apiKey } }
      );
      if (keysRes.ok) setApiKeys(await keysRes.json());

      const usersRes = await fetch(`${API_BASE}/users`, {
        headers: { "logos-key": apiKey },
      });
      if (usersRes.ok) setAllUsers(await usersRes.json());

      if (isLogosAdmin || ownerFlag) {
        const permsRes = await fetch(
          `${API_BASE}/admin/teams/${teamId}/model-permissions`,
          { headers: { "logos-key": apiKey } }
        );
        if (permsRes.ok) {
          const perms = await permsRes.json();
          setTeamModelsCount(perms.length);
        }

        const adminRes = await fetch(`${API_BASE}/users/admins`, {
          headers: { "logos-key": apiKey },
        });
        if (adminRes.ok) setAdminUsers(await adminRes.json());
      }
    } catch (err) {
      router.replace("/team-management");
    } finally {
      setLoading(false);
    }
  }, [teamId, apiKey, isLogosAdmin, router]);

  useEffect(() => {
    fetchAllData();
  }, [fetchAllData]);

  const handleDeleteTeam = async () => {
    setDeleteVisible(false);
    try {
      await fetch(`${API_BASE}/teams/${id}`, {
        method: "DELETE",
        headers: { "logos-key": apiKey },
      });
      router.replace("/team-management");
    } catch {
      alert("Failed to delete team");
    }
  };

  const handleEditNameOpen = () => {
    setEditNameInput(teamName);
    setEditNameError("");
    setEditNameVisible(true);
  };

  const handleSaveName = async () => {
    if (!editNameInput.trim()) {
      setEditNameError("Team name cannot be empty.");
      return;
    }
    setEditNameLoading(true);
    setEditNameError("");

    try {
      const res = await fetch(`${API_BASE}/teams/${teamId}/name`, {
        method: "PATCH",
        headers: { "logos-key": apiKey, "Content-Type": "application/json" },
        body: JSON.stringify({ name: editNameInput.trim() }),
      });
      const data = await res.json();

      if (res.ok) {
        setTeamName(data.name);
        setTeam((prev: any) => ({ ...prev, name: data.name }));
        setEditNameVisible(false);
      } else {
        let errorMsg = "Failed to update team name.";

        if (data.error) {
          if (typeof data.error === "string") {
            errorMsg = data.error;
          } else if (typeof data.error === "object" && data.error.message) {
            errorMsg = data.error.message;
          }
        } else if (typeof data.detail === "string") {
          errorMsg = data.detail;
        }

        setEditNameError(errorMsg);
      }
    } catch (err) {
      setEditNameError("Connection error.");
    } finally {
      setEditNameLoading(false);
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

  const canEdit = isOwner;
  const canEditLimits = isLogosAdmin || isOwner;
  const showApplicationKeysTab = isLogosAdmin || isOwner;
  const showModelsTab = isLogosAdmin || isOwner;
  const showSettingsTab = isLogosAdmin || isOwner;

  const TabButton = ({ tab, label }: { tab: Tab; label: string }) => (
    <Pressable
      onPress={() => setActiveTab(tab)}
      style={{
        paddingVertical: 12,
        paddingHorizontal: 14,
        borderBottomWidth: 2,
        borderBottomColor: activeTab === tab ? "#5B7CFA" : "transparent",
      }}
    >
      <Text
        style={{
          fontWeight: activeTab === tab ? "600" : "400",
          color: activeTab === tab ? "#5B7CFA" : "#6B7280",
        }}
      >
        {label}
      </Text>
    </Pressable>
  );

  return (
    <VStack className="w-full" space="xl">
      <HStack style={{ alignItems: "center" }}>
        <Pressable
          onPress={() => router.push("/team-management")}
          style={{ padding: 4, width: 32 }}
        >
          <Icon as={ArrowLeftIcon} size="md" className="text-typography-600" />
        </Pressable>

        <HStack
          space="sm"
          style={{ flex: 1, justifyContent: "center", alignItems: "center" }}
        >
          <Text
            size="2xl"
            className="font-bold text-black dark:text-white"
            style={{ textAlign: "center" }}
          >
            {teamName}
          </Text>
          {canEdit && (
            <Pressable onPress={handleEditNameOpen} style={{ padding: 4 }}>
              <Icon as={EditIcon} size="sm" className="text-typography-400" />
            </Pressable>
          )}
        </HStack>

        <View style={{ width: 32 }} />
      </HStack>

      <HStack
        style={{
          borderBottomWidth: 1,
          borderBottomColor: "#e2e8f0",
          marginBottom: 16,
        }}
      >
        <TabButton tab="overview" label="Overview" />
        <TabButton tab="members" label="Members" />
        {showApplicationKeysTab && <TabButton tab="application_keys" label="Application Keys" />}
        {showModelsTab && <TabButton tab="models" label="Models" />}
        {showSettingsTab && <TabButton tab="settings" label="Settings" />}
      </HStack>

      {activeTab === "overview" && (
        <Overview_tab
          team={team}
          membersCount={members.length}
          applicationKeysCount={
            apiKeys.filter((k: any) => k.key_type === "application").length
          }
          developerKeysCount={
            apiKeys.filter((k: any) => k.key_type === "developer").length
          }
          teamModelsCount={teamModelsCount}
          budgetUsedMicroCents={team?.budget_used_micro_cents || 0}
        />
      )}

      {activeTab === "members" && (
        <Members_tab
          team={team}
          teamId={teamId}
          teamName={teamName}
          members={members}
          apiKeys={apiKeys.filter((k: any) => k.key_type === "developer")}
          allUsers={allUsers}
          adminUsers={adminUsers}
          isLogosAdmin={isLogosAdmin}
          canEdit={canEdit}
          canEditLimits={canEditLimits}
          currentUserId={currentUserId}
          apiKey={apiKey}
          onRefresh={fetchAllData}
        />
      )}

      {activeTab === "application_keys" && showApplicationKeysTab && (
        <Application_keys_tab
          team={team}
          teamId={teamId}
          apiKeys={apiKeys.filter((k: any) => k.key_type === "application")}
          canEdit={canEdit}
          canEditKeySettings={isLogosAdmin || isOwner}
          onRefresh={fetchAllData}
          apiKey={apiKey}
        />
      )}

      {activeTab === "models" && showModelsTab && (
        <Models_tab teamId={teamId} canEdit={isLogosAdmin || isOwner} apiKey={apiKey} />
      )}

      {activeTab === "settings" && showSettingsTab && (
        <Settings_tab
          team={team}
          canEdit={canEdit}
          canEditLimits={canEditLimits}
          apiKey={apiKey}
          onRefresh={fetchAllData}
          onDeleteTeam={() => setDeleteVisible(true)}
        />
      )}

      <ConfirmDeleteModal
        visible={deleteVisible}
        onClose={() => setDeleteVisible(false)}
        onConfirm={handleDeleteTeam}
        title="Delete Team?"
        message={`Are you sure you want to delete "${teamName}"? This action is permanent.`}
      />

      <BaseModal
        visible={editNameVisible}
        onClose={() => setEditNameVisible(false)}
        maxWidth={400}
      >
        <VStack space="md">
          <Text style={{ fontWeight: "700", fontSize: 18 }}>
            Edit Team Name
          </Text>
          <Input>
            <InputField
              placeholder="Team Name"
              value={editNameInput}
              onChangeText={setEditNameInput}
              onSubmitEditing={handleSaveName}
            />
          </Input>
          {editNameError ? (
            <Text style={{ color: "#e63535", fontSize: 12 }}>
              {editNameError}
            </Text>
          ) : null}
          <HStack space="md" className="mt-2 justify-end">
            <Button variant="outline" onPress={() => setEditNameVisible(false)}>
              <ButtonText>Cancel</ButtonText>
            </Button>
            <Button
              onPress={handleSaveName}
              disabled={editNameLoading || !editNameInput.trim()}
              style={{
                opacity: editNameLoading || !editNameInput.trim() ? 0.5 : 1,
              }}
            >
              <ButtonText>{editNameLoading ? "Saving..." : "Save"}</ButtonText>
            </Button>
          </HStack>
        </VStack>
      </BaseModal>
    </VStack>
  );
}