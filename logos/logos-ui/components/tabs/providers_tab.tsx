import React, { useState, useEffect } from "react";
import {
  View,
  Pressable,
  ScrollView,
  TextInput,
  ActivityIndicator,
} from "react-native";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Text } from "@/components/ui/text";
import { Box } from "@/components/ui/box";
import { Button, ButtonText } from "@/components/ui/button";
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableData,
} from "@/components/ui/table";
import { Icon, TrashIcon, CheckIcon } from "@/components/ui/icon";
import { BaseModal } from "@/components/modals/base-modal";
import { ConfirmDeleteModal } from "@/components/modals/confirm-delete-modal";
import { API_BASE } from "@/components/statistics/constants";

const colStyles: Record<string, any> = {
  name: { width: "85%", minWidth: 150 },
  delete: { width: 48, alignItems: "flex-end" },
};

export function Providers_tab({ teamId, canEdit, apiKey }: any) {
  const [allProviders, setAllProviders] = useState<any[]>([]);
  const [selectedProviderIds, setSelectedProviderIds] = useState<number[]>([]);
  const [loading, setLoading] = useState(true);
  const [addVisible, setAddVisible] = useState(false);
  const [search, setSearch] = useState("");
  const [stagedIds, setStagedIds] = useState<number[]>([]);
  const [deleteVisible, setDeleteVisible] = useState(false);
  const [targetToDelete, setTargetToDelete] = useState<{
    id: number;
    name: string;
  } | null>(null);

  useEffect(() => {
    fetchData();
  }, [teamId]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/logosdb/get_providers`, {
        method: "POST",
        headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({ logos_key: apiKey }),
      });
      const data = await res.json();
      setAllProviders(Array.isArray(data) ? data : []);

      const permsRes = await fetch(
        `${API_BASE}/admin/teams/${teamId}/provider-permissions`,
        {
          headers: { Authorization: `Bearer ${apiKey}` },
        }
      );
      const activeIds = await permsRes.json();
      setSelectedProviderIds(activeIds);
    } catch (e) {
      console.error("Failed to fetch provider permissions", e);
    } finally {
      setLoading(false);
    }
  };

  const updatePermissionsInDB = async (newIds: number[]) => {
    try {
      const res = await fetch(
        `${API_BASE}/admin/teams/${teamId}/provider-permissions`,
        {
          method: "PUT",
          headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
          body: JSON.stringify({ provider_ids: newIds }),
        }
      );
      if (res.ok) {
        setSelectedProviderIds(newIds);
      } else {
        alert("Failed to update permissions.");
      }
    } catch (e) {
      alert("Network error. Failed to update permissions.");
    }
  };

  const toggleStaged = (id: number) => {
    setStagedIds((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]
    );
  };

  const handleAddStaged = () => {
    if (stagedIds.length === 0) return;
    updatePermissionsInDB([...selectedProviderIds, ...stagedIds]);
    setAddVisible(false);
    setSearch("");
    setStagedIds([]);
  };

  const promptRemove = (id: number, name: string) => {
    setTargetToDelete({ id, name });
    setDeleteVisible(true);
  };

  const executeRemove = () => {
    if (!targetToDelete) return;
    updatePermissionsInDB(
      selectedProviderIds.filter((id) => id !== targetToDelete.id)
    );
    setDeleteVisible(false);
    setTargetToDelete(null);
  };

  const teamProviders = allProviders.filter((p) =>
    selectedProviderIds.includes(p.id)
  );
  const availableProviders = allProviders.filter(
    (p) => !selectedProviderIds.includes(p.id)
  );
  const searchTerms = search.toLowerCase().trim().split(/\s+/);

  const filteredAvailable = search.trim()
    ? availableProviders.filter((p) => {
        const name = p?.name || "";
        const searchableText = name.toLowerCase();
        return searchTerms.every((term) => searchableText.includes(term));
      })
    : availableProviders;

  if (loading) {
    return (
      <VStack className="items-center justify-center p-8" space="lg">
        <ActivityIndicator size="large" color="#006DFF" />
        <Text className="text-typography-500">Loading infrastructure...</Text>
      </VStack>
    );
  }

  return (
    <VStack space="xl" style={{ marginTop: 16, paddingBottom: 40 }}>
      <VStack space="sm">
        <HStack
          style={{ justifyContent: "space-between", alignItems: "center" }}
        >
          <Text style={{ fontWeight: "700", fontSize: 16 }}>
            Team Provider Access
          </Text>
          {canEdit && (
            <Button
              size="sm"
              onPress={() => {
                setAddVisible(true);
                setStagedIds([]);
              }}
            >
              <ButtonText>+ Add Providers</ButtonText>
            </Button>
          )}
        </HStack>

        {teamProviders.length === 0 ? (
          <Text style={{ color: "#9ca3af", fontSize: 13, marginTop: 8 }}>
            This team currently has no infrastructure access.
          </Text>
        ) : (
          <Box className="mt-2 w-full overflow-hidden rounded-lg border border-outline-200 bg-secondary-200 p-2">
            <ScrollView horizontal contentContainerStyle={{ flexGrow: 1 }}>
              <Box className="min-w-full">
                <Table className="w-full">
                  <TableHeader>
                    <TableRow className="bg-secondary-200">
                      <TableHead style={colStyles.name}>
                        Provider Name
                      </TableHead>
                      <TableHead style={colStyles.delete}>{""}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {teamProviders.map((prov: any) => (
                      <TableRow key={prov.id} className="bg-secondary-200">
                        <TableData style={colStyles.name}>
                          <VStack
                            space="xs"
                            style={{
                              justifyContent: "center",
                              paddingVertical: 4,
                            }}
                          >
                            <Text
                              style={{ fontWeight: "600", fontSize: 14 }}
                              numberOfLines={1}
                            >
                              {prov.name || "Unnamed"}
                            </Text>

                            {prov.base_url ? (
                              <Text
                                style={{ fontSize: 12, color: "#6b7280" }}
                                numberOfLines={1}
                                ellipsizeMode="tail"
                              >
                                {prov.base_url}
                              </Text>
                            ) : null}
                          </VStack>
                        </TableData>

                        <TableData style={colStyles.delete}>
                          {canEdit && (
                            <Pressable
                              onPress={() =>
                                promptRemove(prov.id, prov.name || "Unnamed")
                              }
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

      <BaseModal
        visible={addVisible}
        onClose={() => {
          setAddVisible(false);
          setSearch("");
          setStagedIds([]);
        }}
        maxWidth={800}
      >
        <VStack space="md" style={{ minWidth: 300 }}>
          <Text style={{ fontWeight: "700", fontSize: 18 }}>
            Add Providers to Team
          </Text>

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
              placeholder="Search available providers..."
              value={search}
              onChangeText={setSearch}
              autoFocus
              style={
                { fontSize: 13, color: "#333", outlineStyle: "none" } as any
              }
              placeholderTextColor="#aaa"
            />
          </View>

          <ScrollView
            style={{ maxHeight: 400 }}
            keyboardShouldPersistTaps="handled"
          >
            <VStack space="xs" style={{ paddingVertical: 4 }}>
              {filteredAvailable.map((prov: any) => {
                const isSelected = stagedIds.includes(prov.id);
                return (
                  <Pressable
                    key={prov.id}
                    onPress={() => toggleStaged(prov.id)}
                    style={{
                      paddingHorizontal: 12,
                      paddingVertical: 10,
                      borderBottomWidth: 1,
                      borderBottomColor: "#f3f4f6",
                      flexDirection: "row",
                      alignItems: "center",
                      backgroundColor: "transparent",
                    }}
                  >
                    <View
                      style={{
                        width: 20,
                        height: 20,
                        borderRadius: 4,
                        borderWidth: 1,
                        alignItems: "center",
                        justifyContent: "center",
                        marginRight: 14,
                        borderColor: isSelected ? "#006DFF" : "#cbd5e1",
                        backgroundColor: isSelected ? "#006DFF" : "transparent",
                      }}
                    >
                      {isSelected && (
                        <Icon as={CheckIcon} size="xs" color="white" />
                      )}
                    </View>

                    <VStack style={{ flex: 1 }}>
                      <Text
                        style={{
                          fontWeight: "600",
                          fontSize: 14,
                          color: "#111827",
                        }}
                      >
                        {prov.name || `Provider #${prov.id}`}
                      </Text>
                      {prov.base_url ? (
                        <Text
                          style={{
                            fontSize: 12,
                            color: "#6b7280",
                            marginTop: 2,
                          }}
                        >
                          {prov.base_url}
                        </Text>
                      ) : null}
                    </VStack>
                  </Pressable>
                );
              })}
              {filteredAvailable.length === 0 && (
                <Text
                  style={{
                    paddingHorizontal: 10,
                    paddingVertical: 16,
                    color: "#9ca3af",
                    fontSize: 13,
                    textAlign: "center",
                  }}
                >
                  {availableProviders.length === 0
                    ? "All providers are already assigned to this team."
                    : "No matching providers found."}
                </Text>
              )}
            </VStack>
          </ScrollView>

          <HStack
            space="md"
            style={{
              justifyContent: "flex-end",
              marginTop: 8,
              paddingTop: 16,
              borderTopWidth: 1,
              borderTopColor: "#e2e8f0",
            }}
          >
            <Button
              variant="outline"
              onPress={() => {
                setAddVisible(false);
                setSearch("");
                setStagedIds([]);
              }}
            >
              <ButtonText>Cancel</ButtonText>
            </Button>
            <Button
              onPress={handleAddStaged}
              disabled={stagedIds.length === 0}
              style={{
                opacity: stagedIds.length === 0 ? 0.5 : 1,
                minWidth: 150,
              }}
            >
              <ButtonText>
                Add Selected{" "}
                {stagedIds.length > 0 ? `(${stagedIds.length})` : ""}
              </ButtonText>
            </Button>
          </HStack>
        </VStack>
      </BaseModal>

      <ConfirmDeleteModal
        visible={deleteVisible}
        onClose={() => {
          setDeleteVisible(false);
          setTargetToDelete(null);
        }}
        onConfirm={executeRemove}
        title="Remove Provider Access?"
        message={`Are you sure you want to remove access to "${targetToDelete?.name}" for this team? Any allowed models strictly hosted here will drop offline.`}
      />
    </VStack>
  );
}
