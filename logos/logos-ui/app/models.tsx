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
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableData,
} from '@/components/ui/table';
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";

export default function Models() {
    const { apiKey } = useAuth();
    const [stats, setStats] = useState<{ totalModels: number; mostUsedModel: string } | null>(null);
    const [models, setModels] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const router = useRouter();

    useEffect(() => {
        if (!apiKey) return;
        loadModels(apiKey);
        loadStats(apiKey);
    }, [apiKey]);

    const loadModels = async (key: string) => {
        try {
            const response = await fetch('https://logos.ase.cit.tum.de:8080/logosdb/get_models', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${key}`,
                    'Content-Type': 'application/json',
                    'logos_key': key,
                },
                body: JSON.stringify({
                    logos_key: key
                })
            });
            const [data, code] = JSON.parse(await response.text());
            if (code === 200) {
                const formattedModels = data.map((model: any[][]) => ({
                    id: model[0],
                    name: model[1],
                    endpoint: model[2],
                    api_id: model[3],
                    weight_privacy: model[4],
                    weight_latency: model[5],
                    weight_accuracy: model[6],
                    weight_cost: model[7],
                    weight_quality: model[8],
                    tags: model[9],
                    parallel: model[10],
                    description: model[11],
                }));
                setModels(formattedModels);
            }
            setLoading(false);
        } catch (e) {
            setModels([]);
            setLoading(false);
        }
    };

    const loadStats = async (key: string) => {
        try {
            const response = await fetch('https://logos.ase.cit.tum.de:8080/logosdb/get_general_model_stats', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${key}`,
                    'Content-Type': 'application/json',
                    'logos_key': key,
                },
                body: JSON.stringify({
                    logos_key: key
                })
            });
            const [data, code] = JSON.parse(await response.text());
            if (code === 200) {
                setStats(data);
            } else {
                setStats({totalModels: 0, mostUsedModel: "None" });
            }
        } catch (e) {
            setStats({totalModels: 0, mostUsedModel: "None" });
        }
    };

    return (
        <VStack className="w-full">
            <Text size="2xl" className="font-bold text-center text-black dark:text-white">
                Models
            </Text>
            <Text className="text-center text-gray-500 mb-6">
                Administrate Models.
            </Text>

            {stats && (
                <HStack space="xl" className="justify-center mb-8">
                    <VStack className="items-center bg-background-50 border border-outline-200 dark:border-none p-4 rounded-xl min-w-[100px]">
                        <Text size="xl" className="font-bold text-black dark:text-white">{stats.totalModels}</Text>
                        <Text size="sm" className="mt-1 text-black dark:text-white">Models</Text>
                    </VStack>
                    <VStack className="items-center bg-background-50 border border-outline-200 dark:border-none p-4 rounded-xl min-w-[100px]">
                        <Text size="xl" className="font-bold text-black dark:text-white">{stats.mostUsedModel}</Text>
                        <Text size="sm" className="mt-1 text-black dark:text-white">Most frequently used Model</Text>
                    </VStack>
                </HStack>
            )}

            <Box className="self-end mb-6">
                <Button onPress={() => router.push('/add_model')}>
                    <ButtonText>+ Add</ButtonText>
                </Button>
            </Box>

            {loading ? (
                <VStack space="lg">
                    <HStack space="xl" className="justify-center">
                        {Array.from({ length: 2 }).map((_, idx) => (
                            <Skeleton
                                key={idx}
                                className="h-[110px] w-[150px] rounded-xl bg-background-200"
                                variant="rounded"
                            />
                        ))}
                    </HStack>

                    <Box className="w-full overflow-hidden border border-outline-200 bg-secondary-200 rounded-lg p-2">
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
                </VStack>
            ) : (
                <Box className="w-full overflow-hidden border border-outline-200 bg-secondary-200 rounded-lg p-2">
                    <ScrollView horizontal contentContainerStyle={{flexGrow: 1}}>
                        <Box className="min-w-full">
                            <ModelsTable models={models} />
                        </Box>
                    </ScrollView>
                </Box>
            )}
        </VStack>
    );
};

const ModelsTable = ({ models }: { models: any[] }) => {
    return (
        <Table className="w-full">
            <TableHeader>
                <TableRow className="bg-secondary-200">
                    <TableHead>ID</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead>Endpoint</TableHead>
                    <TableHead>API-ID</TableHead>
                    <TableHead>Privacy</TableHead>
                    <TableHead>Latency</TableHead>
                    <TableHead>Accuracy</TableHead>
                    <TableHead>Cost</TableHead>
                    <TableHead>Quality</TableHead>
                    <TableHead>Tags</TableHead>
                    <TableHead>Parallel</TableHead>
                    <TableHead>Description</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {models.map((model) => (
                    <TableRow key={model.id} className="bg-secondary-200">
                        <TableData>{model.id}</TableData>
                        <TableData>{model.name}</TableData>
                        <TableData>{model.endpoint}</TableData>
                        <TableData>{model.api_id}</TableData>
                        <TableData>{model.weight_privacy}</TableData>
                        <TableData>{model.weight_latency}</TableData>
                        <TableData>{model.weight_accuracy}</TableData>
                        <TableData>{model.weight_cost}</TableData>
                        <TableData>{model.weight_quality}</TableData>
                        <TableData>{model.tags}</TableData>
                        <TableData>{model.parallel?.toString()}</TableData>
                        <TableData>{model.description}</TableData>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    );
};
