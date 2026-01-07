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
import { ActivityIndicator } from 'react-native';

type Provider = {
  id: number;
  name: string;
  baseUrl: string;
  authName: string;
  authFormat: string;
};

export default function Providers() {
  const { apiKey } = useAuth();
  const [stats, setStats] = useState<{ totalProviders: number; mostUsedProvider: string } | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    if (!apiKey) return;
    loadProviders(apiKey);
    loadStats(apiKey);
  }, [apiKey]);

  const loadProviders = async (key: string) => {
    try {
      setLoading(true);
      const response = await fetch('https://logos.ase.cit.tum.de:8080/logosdb/get_providers', {
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
        const formattedProviders = data.map((provider: any[][]) => ({
          id: provider[0],
          name: provider[1],
          baseUrl: provider[2],
          authName: provider[3],
          authFormat: provider[4],
        }));
        setProviders(formattedProviders);
      } else {
        setProviders([]);
      }
    } catch (e) {
      setProviders([]);
    } finally {
      setLoading(false);
    }
  };

  const loadStats = async (key: string) => {
    try {
      const response = await fetch('https://logos.ase.cit.tum.de:8080/logosdb/get_general_provider_stats', {
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
        setStats(data);
      } else {
        setStats({ totalProviders: 0, mostUsedProvider: 'None' });
      }
    } catch (e) {
      setStats({ totalProviders: 0, mostUsedProvider: 'None' });
    }
  };

  return (
    <VStack className="w-full space-y-6">
      <VStack className="space-y-1">
        <Text size="2xl" className="font-bold text-center text-black dark:text-white">
          Providers
        </Text>
        <Text className="text-center text-gray-500 dark:text-gray-300">
          Administrate providers.
        </Text>
      </VStack>

      {stats && (
        <HStack space="xl" className="justify-center">
          <VStack className="items-center bg-background-50 border border-outline-200 dark:border-none p-4 rounded-xl min-w-[120px]">
            <Text size="xl" className="font-bold text-black dark:text-white">
              {stats.totalProviders}
            </Text>
            <Text size="sm" className="mt-1 text-black dark:text-white">Provider(s)</Text>
          </VStack>
          <VStack className="items-center bg-background-50 border border-outline-200 dark:border-none p-4 rounded-xl min-w-[120px]">
            <Text size="xl" className="font-bold text-black dark:text-white">
              {stats.mostUsedProvider}
            </Text>
            <Text size="sm" className="mt-1 text-black dark:text-white">Most frequently used</Text>
          </VStack>
        </HStack>
      )}

      <Box className="self-end">
        <Button onPress={() => router.push('/add_provider')}>
          <ButtonText>+ Add</ButtonText>
        </Button>
      </Box>

      {loading ? (
        <VStack space="lg" className="items-center justify-center p-8">
            <ActivityIndicator size="large" color="#006DFF" />
            <Text className="text-gray-500 mt-2">Loading providers...</Text>
        </VStack>
      ) : (
        <Box className="w-full overflow-hidden border border-outline-200 bg-secondary-200 rounded-lg p-2">
          <ScrollView horizontal contentContainerStyle={{ flexGrow: 1 }}>
            <Box className="min-w-full">
              <ProvidersTable providers={providers} />
            </Box>
          </ScrollView>
        </Box>
      )}
    </VStack>
  );
};

const ProvidersTable = ({ providers }: { providers: Provider[] }) => {
  return (
    <Table className="w-full bg-secondary-200">
      <TableHeader>
        <TableRow className="bg-secondary-200">
          <TableHead>ID</TableHead>
          <TableHead>Name</TableHead>
          <TableHead>Base URL</TableHead>
          <TableHead>Auth Name</TableHead>
          <TableHead>Auth Format</TableHead>
          <TableHead>API Key</TableHead>
          <TableHead>Models</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {providers.map((provider) => (
          <TableRow key={provider.id} className="bg-secondary-200">
            <TableData>{provider.id}</TableData>
            <TableData>{provider.name}</TableData>
            <TableData>{provider.baseUrl}</TableData>
            <TableData>{provider.authName}</TableData>
            <TableData>{provider.authFormat}</TableData>
            <TableData>—</TableData>
            <TableData>0</TableData>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
};
