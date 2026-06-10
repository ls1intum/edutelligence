import React, { useEffect, useState } from "react";
import { ScrollView } from "react-native";
import { useRouter } from "expo-router";

import { useAuth } from "@/components/auth-shell";
import { API_BASE } from "@/components/statistics/constants";
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Button, ButtonText } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableData,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ActivityIndicator } from "react-native";

type Policy = {
  id: number;
  api_key_id: number | null;
  team_id: number | null;
  name: string;
  description: string;
  threshold_privacy: string;
  threshold_latency: number;
  threshold_accuracy: number;
  threshold_cost: number;
  threshold_quality: number;
  priority: number;
  topic: string;
};

export default function Policies() {
  const { apiKey } = useAuth();
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    if (!apiKey) return;
    loadPolicies(apiKey);
  }, [apiKey]);

  const loadPolicies = async (key: string) => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE}/logosdb/get_policies`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${key}`,
          "Content-Type": "application/json",
        },
      });
      if (response.ok) {
        const data: Policy[] = await response.json();
        setPolicies(data);
      } else {
        setPolicies([]);
      }
    } catch (e) {
      setPolicies([]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <VStack className="w-full space-y-6">
      <VStack className="space-y-1">
        <Text
          size="2xl"
          className="text-center font-bold text-black dark:text-white"
        >
          Policies
        </Text>
        <Text className="text-center text-gray-500 dark:text-gray-300">
          Administrate policies.
        </Text>
      </VStack>

      <Box className="self-end">
        <Button onPress={() => router.push("/policies")}>
          <ButtonText>+ Add</ButtonText>
        </Button>
      </Box>

      {loading ? (
        <Box className="w-full items-center justify-center overflow-hidden rounded-lg border border-outline-200 bg-secondary-200 p-8">
          <ActivityIndicator size="large" color="#006DFF" />
          <Text className="mt-2 text-gray-500">Loading policies...</Text>
        </Box>
      ) : (
        <Box className="w-full overflow-hidden rounded-lg border border-outline-200 bg-secondary-200 p-2">
          <ScrollView horizontal contentContainerStyle={{ flexGrow: 1 }}>
            <Box className="min-w-full bg-background-500">
              <PoliciesTable policies={policies} />
            </Box>
          </ScrollView>
        </Box>
      )}
    </VStack>
  );
}

const PoliciesTable = ({ policies }: { policies: Policy[] }) => {
  return (
    <Table className="w-full bg-secondary-200">
      <TableHeader>
        <TableRow className="bg-secondary-200">
          <TableHead>ID</TableHead>
          <TableHead>API Key ID</TableHead>
          <TableHead>Team ID</TableHead>
          <TableHead>Name</TableHead>
          <TableHead>Description</TableHead>
          <TableHead>Threshold Privacy</TableHead>
          <TableHead>Threshold Latency</TableHead>
          <TableHead>Threshold Accuracy</TableHead>
          <TableHead>Threshold Cost</TableHead>
          <TableHead>Threshold Quality</TableHead>
          <TableHead>Priority</TableHead>
          <TableHead>Topic</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {policies.map((policy) => (
          <TableRow key={policy.id} className="bg-secondary-200">
            <TableData>{policy.id}</TableData>
            <TableData>
              {policy.api_key_id !== null ? policy.api_key_id : "-"}
            </TableData>
            <TableData>
              {policy.team_id !== null ? policy.team_id : "-"}
            </TableData>
            <TableData>{policy.name}</TableData>
            <TableData>{policy.description}</TableData>
            <TableData>{policy.threshold_privacy}</TableData>
            <TableData>{policy.threshold_latency}</TableData>
            <TableData>{policy.threshold_accuracy}</TableData>
            <TableData>{policy.threshold_cost}</TableData>
            <TableData>{policy.threshold_quality}</TableData>
            <TableData>{policy.priority}</TableData>
            <TableData>{policy.topic}</TableData>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
};
