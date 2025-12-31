import React, { useEffect, useState } from 'react';
import { ScrollView } from 'react-native';
import { useRouter } from "expo-router";

import { useAuth } from '@/components/auth-shell';
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
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";

type Policy = {
  id: number;
  entity_id: number;
  name: string;
  description: string;
  threshold_privacy: number;
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
      const response = await fetch('https://logos.ase.cit.tum.de:8080/logosdb/get_policies', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${key}`,
          'Content-Type': 'application/json',
          'logos_key': key,
        },
        body: JSON.stringify({
          logos_key: key,
        }),
      });
      const [data, code] = JSON.parse(await response.text());
      if (code === 200) {
        const formattedPolicies = data.map((policy: any[][]) => ({
          id: policy[0],
          entity_id: policy[1],
          name: policy[2],
          description: policy[3],
          threshold_privacy: policy[4],
          threshold_latency: policy[5],
          threshold_accuracy: policy[6],
          threshold_cost: policy[7],
          threshold_quality: policy[8],
          priority: policy[9],
          topic: policy[10],
        }));
        setPolicies(formattedPolicies);
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
        <Text size="2xl" className="font-bold text-center text-black dark:text-white">
          Policies
        </Text>
        <Text className="text-center text-gray-500 dark:text-gray-300">
          Administrate policies.
        </Text>
      </VStack>

      <Box className="self-end">
        <Button onPress={() => router.push('/policies')}>
          <ButtonText>+ Add</ButtonText>
        </Button>
      </Box>

      {loading ? (
        <Box className="w-full overflow-hidden border border-outline-200 rounded-lg p-2 bg-secondary-200">
          <VStack space="sm">
            <Skeleton className="h-10 w-full rounded-md bg-background-200" variant="rounded" />
            {Array.from({ length: 5 }).map((_, idx) => (
              <Skeleton
                key={idx}
                className="h-9 w-full rounded-md bg-background-200"
                variant="rounded"
              />
            ))}
            <SkeletonText _lines={2} className="h-3 bg-background-200 rounded-md" />
          </VStack>
        </Box>
      ) : (
        <Box className="w-full overflow-hidden border border-outline-200 rounded-lg p-2 bg-secondary-200">
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
          <TableHead>Service ID</TableHead>
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
          <TableRow key={policy.id} className= "bg-secondary-200">
            <TableData>{policy.id}</TableData>
            <TableData>{policy.entity_id}</TableData>
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
