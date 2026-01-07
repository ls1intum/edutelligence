import React, { useEffect, useState } from 'react';
import { useAuth } from '@/components/auth-shell';
import { Box } from "@/components/ui/box";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Text } from "@/components/ui/text";
import { Center } from "@/components/ui/center";
import { ActivityIndicator } from 'react-native';

export default function Dashboard() {
    const { apiKey } = useAuth();
    const [stats, setStats] = useState<{ models: number; requests: number; users: number } | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        console.log('[Dashboard] Mounted');
        const fetchStats = async () => {
            if (!apiKey) return;
            try {
                const response = await fetch('https://logos.ase.cit.tum.de:8080/logosdb/generalstats', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'logos_key': apiKey,
                        'Authorization': `Bearer ${apiKey}`,
                    },
                    body: JSON.stringify({
                      logos_key: apiKey
                    })
                });
                const text = await response.text();
                console.log('[Dashboard] stats response text:', text);
                const [data, code] = JSON.parse(text);
                console.log('[Dashboard] stats code:', code);
                if (code === 200) {
                    setStats({
                        models: data.models,
                        requests: data.requests,
                        users: data.users
                    });
                } else {
                    setStats({
                        models: -1,
                        requests: -1,
                        users: -1
                    });
                    console.warn('[Dashboard] Stats returned non-200 code:', code);
                }
            } catch (e) {
                setStats({
                    models: -1,
                    requests: -1,
                    users: -1
                });
                console.error('Error while loading statistics:', e);
            } finally {
                setLoading(false);
            }
        };
        fetchStats();
        return () => console.log('[Dashboard] Unmounting');
    }, [apiKey]);

    return (
        <VStack className="w-full">
            <Text size="2xl" className="font-bold mb-6 self-center">
                Logos-Dashboard
            </Text>

            {loading ? (
                <VStack className="w-full items-center justify-center p-8 text-center" space="lg">
                    <ActivityIndicator size="large" color="#006DFF" />
                    <Text className="text-gray-500 mt-2">Loading dashboard...</Text>
                </VStack>
            ) : stats ? (
                <HStack space="xl" className="justify-center gap-6 mb-8 w-full">
                    <VStack className="items-center bg-background-50 border border-outline-200 dark:border-none p-4 rounded-2xl min-w-[100px]">
                        <Text size="xl" className="font-bold text-black dark:text-white">{stats.models}</Text>
                        <Text size="sm" className="mt-1 text-black dark:text-white">Models</Text>
                    </VStack>
                    <VStack className="items-center bg-background-50 border border-outline-200 dark:border-none p-4 rounded-2xl min-w-[100px]">
                        <Text size="xl" className="font-bold text-black dark:text-white">{stats.requests}</Text>
                        <Text size="sm" className="mt-1 text-black dark:text-white">Requests</Text>
                    </VStack>
                    <VStack className="items-center bg-background-50 border border-outline-200 dark:border-none p-4 rounded-2xl min-w-[100px]">
                        <Text size="xl" className="font-bold text-black dark:text-white">{stats.users}</Text>
                        <Text size="sm" className="mt-1 text-black dark:text-white">User</Text>
                    </VStack>
                </HStack>
            ) : (
                <Text className="mt-5 text-red-500">Error while loading statistics.</Text>
            )}

            <Box className="mt-5 self-center p-5 rounded-[30px] border border-[#aaa]">
                <Text className="text-black dark:text-white">
                    Hier erscheinen bald anpassbare Informationsboxen...
                </Text>
            </Box>
        </VStack>
    );
};
