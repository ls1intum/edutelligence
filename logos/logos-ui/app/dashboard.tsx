import React, { useEffect, useState } from "react";
import { useAuth } from "@/components/auth-shell";
import { API_BASE } from "@/components/statistics/constants";
import { Box } from "@/components/ui/box";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Text } from "@/components/ui/text";
import { Center } from "@/components/ui/center";
import { ActivityIndicator } from "react-native";

export default function Dashboard() {
  const { apiKey } = useAuth();
  const [stats, setStats] = useState<{
    models: number;
    requests: number;
    users: number;
  } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    console.log("[Dashboard] Mounted");
    const fetchStats = async () => {
      if (!apiKey) return;
      try {
        const response = await fetch(
          `${API_BASE}/logosdb/generalstats`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              logos_key: apiKey,
              Authorization: `Bearer ${apiKey}`,
            },
            body: JSON.stringify({
              logos_key: apiKey,
            }),
          }
        );
        const text = await response.text();
        console.log("[Dashboard] stats response text:", text);
        const [data, code] = JSON.parse(text);
        console.log("[Dashboard] stats code:", code);
        if (code === 200) {
          setStats({
            models: data.models,
            requests: data.requests,
            users: data.users,
          });
        } else {
          setStats({
            models: -1,
            requests: -1,
            users: -1,
          });
          console.warn("[Dashboard] Stats returned non-200 code:", code);
        }
      } catch (e) {
        setStats({
          models: -1,
          requests: -1,
          users: -1,
        });
        console.error("Error while loading statistics:", e);
      } finally {
        setLoading(false);
      }
    };
    fetchStats();
    return () => console.log("[Dashboard] Unmounting");
  }, [apiKey]);

  return (
    <VStack className="w-full" space="lg">
      <Text size="2xl" className="text-center font-bold text-black dark:text-white">
        Dashboard
      </Text>

      {loading ? (
        <VStack
          className="items-center justify-center p-8"
          space="lg"
        >
          <ActivityIndicator size="large" color="#006DFF" />
          <Text className="mt-2 text-gray-500">Loading dashboard...</Text>
        </VStack>
      ) : stats ? (
        <HStack space="xl" className="w-full justify-center gap-6">
          <VStack className="min-w-[120px] items-center rounded-xl border border-outline-200 bg-background-50 p-4 dark:border-none">
            <Text size="xl" className="font-bold text-black dark:text-white">
              {stats.models}
            </Text>
            <Text size="sm" className="mt-1 text-black dark:text-white">
              Models
            </Text>
          </VStack>
          <VStack className="min-w-[120px] items-center rounded-xl border border-outline-200 bg-background-50 p-4 dark:border-none">
            <Text size="xl" className="font-bold text-black dark:text-white">
              {stats.requests}
            </Text>
            <Text size="sm" className="mt-1 text-black dark:text-white">
              Requests
            </Text>
          </VStack>
          <VStack className="min-w-[120px] items-center rounded-xl border border-outline-200 bg-background-50 p-4 dark:border-none">
            <Text size="xl" className="font-bold text-black dark:text-white">
              {stats.users}
            </Text>
            <Text size="sm" className="mt-1 text-black dark:text-white">
              User
            </Text>
          </VStack>
        </HStack>
      ) : (
        <Text className="mt-5 text-red-500">
          Error while loading statistics.
        </Text>
      )}

      <Box className="self-center rounded-2xl border border-outline-200 p-5 dark:border-outline-800 dark:bg-[#111]">
        <Text className="mb-1 font-semibold text-black dark:text-white">Customizable information boxes</Text>
        <Text className="text-gray-500 self-center dark:text-gray-400">Coming soon</Text>
      </Box>
    </VStack>
  );
}
