import React, { useState, useEffect, useCallback } from "react";
import { Pressable, View, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useAuth } from "@/components/auth-shell";
import { API_BASE, User } from "@/components/statistics/constants";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Icon, ArrowLeftIcon } from "@/components/ui/icon";
import { ConfirmDeleteModal } from "@/components/modals/confirm-delete-modal";

import { Overview_tab } from "@/components/tabs/overview_tab";
import { Members_tab } from "@/components/tabs/members_tab";
import { Keys_tab } from "@/components/tabs/keys_tab";
import { Models_tab } from "@/components/tabs/models_tab";
import { Settings_tab } from "@/components/tabs/settings_tab";

type Tab = "overview" | "members" | "keys" | "models" | "settings";

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
      }
    } catch (err) {
      router.replace("/team-management");
    } finally {
      setLoading(false);
    }
  }, [teamId, apiKey, isLogosAdmin, router]);

  useEffect(() => {
    fetchAllData();

    if (isLogosAdmin) {
      fetch(`${API_BASE}/users/admins`, { headers: { "logos-key": apiKey } })
        .then((r) => (r.ok ? r.json() : []))
        .then(setAdminUsers)
        .catch(() => setAdminUsers([]));
    }
  }, [fetchAllData, apiKey, isLogosAdmin]);

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

  if (loading) {
    return (
      <VStack className="items-center justify-center p-8" space="lg">
        <ActivityIndicator size="large" color="#006DFF" />
        <Text className="text-gray-500">Loading team...</Text>
      </VStack>
    );
  }

  const canEdit = isOwner;
  const canEditLimits = isLogosAdmin;
  const showKeysTab = isLogosAdmin || isOwner;
  const showModelsTab = isLogosAdmin || isOwner;
  const showSettingsTab = isLogosAdmin;

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
        <Text
          size="2xl"
          className="font-bold text-black dark:text-white"
          style={{ flex: 1, textAlign: "center" }}
        >
          {teamName}
        </Text>
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
        {showKeysTab && <TabButton tab="keys" label="Keys" />}
        {showModelsTab && <TabButton tab="models" label="Models" />}
        {showSettingsTab && <TabButton tab="settings" label="Settings" />}
      </HStack>

      {activeTab === "overview" && (
        <Overview_tab
          team={team}
          membersCount={members.length}
          serviceKeysCount={
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
          currentUserId={currentUserId}
          apiKey={apiKey}
          onRefresh={fetchAllData}
        />
      )}

      {activeTab === "keys" && showKeysTab && (
        <Keys_tab
          team={team}
          teamId={teamId}
          apiKeys={apiKeys.filter((k: any) => k.key_type === "application")}
          canEdit={canEdit}
          canEditKeySettings={isLogosAdmin}
          onRefresh={fetchAllData}
          apiKey={apiKey}
        />
      )}

      {activeTab === "models" && showModelsTab && (
        <Models_tab teamId={teamId} canEdit={isLogosAdmin} apiKey={apiKey} />
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
    </VStack>
  );
}