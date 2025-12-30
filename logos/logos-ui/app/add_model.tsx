import React, { useEffect, useState } from 'react';
import { ActivityIndicator } from 'react-native';
import { useRouter } from "expo-router";

import { useAuth } from '@/components/auth-shell';
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Input, InputField } from "@/components/ui/input";
import { Button, ButtonText } from "@/components/ui/button";
import {
  Select,
  SelectBackdrop,
  SelectContent,
  SelectInput,
  SelectItem,
  SelectPortal,
  SelectTrigger,
} from "@/components/ui/select";
import { Center } from "@/components/ui/center";

const privacyOptions = [
  'LOCAL',
  'CLOUD_IN_EU_BY_US_PROVIDER',
  'CLOUD_NOT_IN_EU_BY_US_PROVIDER',
  'CLOUD_IN_EU_BY_EU_PROVIDER',
];

type WeightKeys = 'latency' | 'accuracy' | 'cost' | 'quality';

type ModelOption = { id: number; name: string };

export default function AddModel() {
  const router = useRouter();
  const { apiKey } = useAuth();
  const [loadingModels, setLoadingModels] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const [models, setModels] = useState<ModelOption[]>([]);
  const [name, setName] = useState('');
  const [endpoint, setEndpoint] = useState('');
  const [tags, setTags] = useState('');
  const [parallel, setParallel] = useState('1');
  const [privacy, setPrivacy] = useState('LOCAL');
  const [weights, setWeights] = useState<Record<WeightKeys, string>>({
    latency: '',
    accuracy: '',
    cost: '',
    quality: '',
  });

  useEffect(() => {
    if (!apiKey) return;
    loadModels(apiKey);
  }, [apiKey]);

  const loadModels = async (key: string) => {
    try {
      setLoadingModels(true);
      const response = await fetch('https://logos.ase.cit.tum.de:8080/logosdb/get_models', {
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
        const formattedModels = data.map((model: any[][]) => ({
          id: model[0],
          name: model[1],
        }));
        setModels(formattedModels);
      } else {
        setModels([]);
      }
    } catch (e) {
      setModels([]);
    } finally {
      setLoadingModels(false);
    }
  };

  const handleSubmit = async () => {
    if (!name || !endpoint) {
      setStatusMessage('Please fill in the required fields.');
      return;
    }

    const payload = {
      name,
      endpoint,
      tags,
      parallel: parseInt(parallel, 10) || 1,
      weight_privacy: privacy,
      weight_latency: 0,
      weight_accuracy: 0,
      weight_cost: 0,
      weight_quality: 0,
      compare_latency: weights.latency,
      compare_accuracy: weights.accuracy,
      compare_cost: weights.cost,
      compare_quality: weights.quality,
      logos_key: apiKey,
    };

    try {
      setSubmitting(true);
      setStatusMessage(null);
      const res = await fetch('https://logos.ase.cit.tum.de:8080/logosdb/add_model', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${apiKey}`,
          'logos_key': apiKey,
        },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        setStatusMessage('Model added successfully.');
        setName('');
        setEndpoint('');
        setTags('');
        setParallel('1');
        setPrivacy('LOCAL');
        setWeights({ latency: '', accuracy: '', cost: '', quality: '' });
        loadModels(apiKey);
      } else {
        setStatusMessage('Could not add the model. Please try again.');
      }
    } catch (e) {
      setStatusMessage('Unexpected error while adding the model.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <VStack className="w-full space-y-6">
      <VStack className="space-y-1">
        <Text size="2xl" className="font-bold text-center text-black dark:text-white">
          Add Model
        </Text>
        <Text className="text-center text-gray-500 dark:text-gray-300">
          Add a new model to Logos
        </Text>
      </VStack>

      <Box className="bg-secondary-200 border border-outline-200 rounded-2xl p-6 space-y-6">
        <HStack className="gap-6 flex-col md:flex-row">
          <VStack className="flex-1 space-y-4">
            <Field
              label="Name"
              helper="Unique model name"
              value={name}
              onChangeText={setName}
              placeholder="LLM-1"
            />
            <Field
              label="Endpoint"
              helper="Model endpoint URL"
              value={endpoint}
              onChangeText={setEndpoint}
              placeholder="https://example.com/invoke"
            />
            <Field
              label="Tags"
              helper='Keywords separated by ";"'
              value={tags}
              onChangeText={setTags}
              placeholder="fast;creative;gpt"
            />
            <Field
              label="Parallelism"
              helper="Maximum parallel requests"
              value={parallel}
              onChangeText={setParallel}
              keyboardType="numeric"
              placeholder="1"
            />

            <Box className="space-y-2">
              <Text className="text-sm font-semibold text-black dark:text-white">
                Privacy Weight
              </Text>
              <Select
                selectedValue={privacy}
                onValueChange={(val) => setPrivacy(val || 'LOCAL')}
              >
                <SelectTrigger className="border border-outline-200 dark:border-outline-700 rounded-md px-3 py-2 bg-white dark:bg-[#1b1b1b]">
                  <SelectInput
                    placeholder="Select privacy"
                    value={privacy}
                    className="text-black dark:text-white"
                  />
                </SelectTrigger>
                <SelectPortal>
                  <SelectBackdrop />
                  <SelectContent className="bg-white dark:bg-[#111] border border-outline-200 dark:border-outline-700">
                    {privacyOptions.map((opt) => (
                      <SelectItem key={opt} label={opt} value={opt} />
                    ))}
                  </SelectContent>
                </SelectPortal>
              </Select>
            </Box>
          </VStack>

          <VStack className="flex-1 space-y-4">
            <Text className="text-base font-semibold text-black dark:text-white">
              Compare weights
            </Text>
            {(['latency', 'accuracy', 'cost', 'quality'] as WeightKeys[]).map((key) => (
              <Box key={key} className="space-y-2">
                <Text className="text-sm font-semibold capitalize text-black dark:text-white">
                  {key} weight
                </Text>
                {loadingModels ? (
                  <Center className="h-10">
                    <ActivityIndicator size="small" color="#666" />
                  </Center>
                ) : (
                  <Select
                    selectedValue={weights[key]}
                    onValueChange={(val) =>
                      setWeights((prev) => ({ ...prev, [key]: val || '' }))
                    }
                  >
                    <SelectTrigger className="border border-outline-200 dark:border-outline-700 rounded-md px-3 py-2 bg-white dark:bg-[#1b1b1b]">
                      <SelectInput
                        placeholder="No model selected"
                        value={
                          models.find((m) => m.id.toString() === weights[key])?.name ||
                          ''
                        }
                        className="text-black dark:text-white"
                      />
                    </SelectTrigger>
                    <SelectPortal>
                      <SelectBackdrop />
                      <SelectContent className="bg-white dark:bg-[#111] border border-outline-200 dark:border-outline-700">
                        <SelectItem label="None" value="" />
                        {models.map((m) => (
                          <SelectItem key={m.id} label={m.name} value={m.id.toString()} />
                        ))}
                      </SelectContent>
                    </SelectPortal>
                  </Select>
                )}
              </Box>
            ))}
          </VStack>
        </HStack>

        <HStack className="justify-between items-center flex-wrap gap-3">
          {statusMessage && (
            <Text className="text-sm text-gray-700 dark:text-gray-300">
              {statusMessage}
            </Text>
          )}
          <HStack className="gap-3">
            <Button
              onPress={handleSubmit}
              isDisabled={submitting}
              action="primary"
            >
              {submitting ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <ButtonText>Add Model</ButtonText>
              )}
            </Button>
            <Button
              variant="solid"
              action="negative"
              onPress={() => router.push('/models')}
            >
              <ButtonText>Cancel</ButtonText>
            </Button>
          </HStack>
        </HStack>
      </Box>
    </VStack>
  );
}

type FieldProps = {
  label: string;
  helper?: string;
  value: string;
  onChangeText: (val: string) => void;
  placeholder?: string;
  keyboardType?: 'default' | 'numeric';
};

const Field = ({
  label,
  helper,
  value,
  onChangeText,
  placeholder,
  keyboardType = 'default',
}: FieldProps) => {
  return (
    <Box className="space-y-2">
      <Text className="text-sm font-semibold text-black dark:text-white">{label}</Text>
      <Input className="bg-white dark:bg-[#1b1b1b] border border-outline-200 dark:border-outline-700">
        <InputField
          value={value}
          onChangeText={onChangeText}
          placeholder={placeholder}
          keyboardType={keyboardType}
          className="text-black dark:text-white placeholder:text-gray-500 dark:placeholder:text-gray-400"
        />
      </Input>
      {helper && (
        <Text className="text-xs text-gray-500 dark:text-gray-400">{helper}</Text>
      )}
    </Box>
  );
};
