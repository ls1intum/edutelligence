import React, { useState } from 'react';
import { ActivityIndicator } from 'react-native';
import { useRouter } from "expo-router";

import { useAuth } from '@/components/auth-shell';
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Input, InputField } from "@/components/ui/input";
import { Button, ButtonText } from "@/components/ui/button";

type FieldProps = {
  label: string;
  value: string;
  onChangeText: (val: string) => void;
  placeholder?: string;
};

export default function AddProvider() {
  const router = useRouter();
  const { apiKey } = useAuth();
  const [submitting, setSubmitting] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const [name, setName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [providerKey, setProviderKey] = useState('');
  const [authName, setAuthName] = useState('');
  const [authFormat, setAuthFormat] = useState('');

  const handleSubmit = async () => {
    if (!name || !baseUrl || !providerKey) {
      setStatusMessage('Name, Base URL, and API Key are required.');
      return;
    }

    const payload = {
      name,
      base_url: baseUrl,
      api_key: providerKey,
      auth_name: authName,
      auth_format: authFormat,
      logos_key: apiKey,
    };

    try {
      setSubmitting(true);
      setStatusMessage(null);
      const res = await fetch('https://logos.ase.cit.tum.de:8080/logosdb/add_provider', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${apiKey}`,
          'logos_key': apiKey,
        },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        setStatusMessage('Provider added successfully.');
        setName('');
        setBaseUrl('');
        setProviderKey('');
        setAuthName('');
        setAuthFormat('');
      } else {
        setStatusMessage('Could not add the provider. Please try again.');
      }
    } catch (e) {
      setStatusMessage('Unexpected error while adding the provider.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <VStack className="w-full space-y-6">
      <VStack className="space-y-1">
        <Text size="2xl" className="font-bold text-center text-black dark:text-white">
          Add Provider
        </Text>
        <Text className="text-center text-gray-500 dark:text-gray-300">
          Register a new provider connection.
        </Text>
      </VStack>

      <Box className="bg-secondary-200 border border-outline-200 rounded-2xl p-6 space-y-5">
        <VStack className="space-y-4">
          <FormField
            label="Provider Name"
            value={name}
            onChangeText={setName}
            placeholder="Azure OpenAI"
          />
          <FormField
            label="Base URL"
            value={baseUrl}
            onChangeText={setBaseUrl}
            placeholder="https://api.example.com"
          />
          <FormField
            label="API Key"
            value={providerKey}
            onChangeText={setProviderKey}
            placeholder="sk-..."
          />
          <FormField
            label="Auth Header Name"
            value={authName}
            onChangeText={setAuthName}
            placeholder="Authorization"
          />
          <FormField
            label="Auth Header Format"
            value={authFormat}
            onChangeText={setAuthFormat}
            placeholder="Bearer {apiKey}"
          />
        </VStack>

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
                <ButtonText>Add Provider</ButtonText>
              )}
            </Button>
            <Button
              variant="solid"
              action="negative"
              onPress={() => router.push('/providers')}
            >
              <ButtonText>Cancel</ButtonText>
            </Button>
          </HStack>
        </HStack>
      </Box>
    </VStack>
  );
}

const FormField = ({ label, value, onChangeText, placeholder }: FieldProps) => (
  <Box className="space-y-2">
    <Text className="text-sm font-semibold text-black dark:text-white">{label}</Text>
    <Input className="bg-white dark:bg-[#1b1b1b] border border-outline-200 dark:border-outline-700">
      <InputField
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        className="text-black dark:text-white placeholder:text-gray-500 dark:placeholder:text-gray-400"
      />
    </Input>
  </Box>
);
