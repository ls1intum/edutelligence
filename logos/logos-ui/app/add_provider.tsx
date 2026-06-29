import React, { useEffect, useState } from "react";
import { ActivityIndicator, Pressable } from "react-native";
import { useRouter } from "expo-router";

import { useAuth } from "@/components/auth-shell";
import { API_BASE } from "@/components/statistics/constants";
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Input, InputField } from "@/components/ui/input";
import { Button, ButtonText } from "@/components/ui/button";
import { Icon, TrashIcon } from "@/components/ui/icon";
import {
  Select,
  SelectBackdrop,
  SelectContent,
  SelectInput,
  SelectItem,
  SelectPortal,
  SelectTrigger,
} from "@/components/ui/select";
import { ModelPicker } from "@/components/model-picker";

type FieldProps = {
  label: string;
  value: string;
  onChangeText: (val: string) => void;
  placeholder?: string;
  helper?: string;
};

const privacyOptions = [
  "LOCAL",
  "CLOUD_IN_EU_BY_US_PROVIDER",
  "CLOUD_NOT_IN_EU_BY_US_PROVIDER",
  "CLOUD_IN_EU_BY_EU_PROVIDER",
];

const providerTypeOptions = ["logosnode", "cloud"];

const cloudProviderTypeOptions = [
  "azure",
  "openai",
  "anthropic",
  "gemini",
  "bedrock",
  "deepseek",
  "groq",
  "none",
];

export default function AddProvider() {
  const router = useRouter();
  const { apiKey } = useAuth();
  const [submitting, setSubmitting] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [providerKey, setProviderKey] = useState("");
  const [authName, setAuthName] = useState("");
  const [authFormat, setAuthFormat] = useState("");
  const [providerType, setProviderType] = useState("logosnode");
  const [cloudProviderType, setCloudProviderType] = useState("none");
  const [privacy, setPrivacy] = useState("LOCAL");
  const [models, setModels] = useState<{ id: number; name: string }[]>([]);

  const [connections, setConnections] = useState<
    { modelId: string; endpoint: string; apiKey: string }[]
  >([]);

  const updateConn = (
    index: number,
    field: "modelId" | "endpoint" | "apiKey",
    val: string
  ) =>
    setConnections((previousConnections) =>
      previousConnections.map((connection, currentIndex) => (currentIndex === index ? { ...connection, [field]: val } : connection))
    );

  const addConn = () =>
    setConnections((previousConnection) => [
      ...previousConnection,
      { modelId: "", endpoint: "", apiKey: "" },
    ]);

  const removeConn = (index: number) =>
    setConnections((previousConnection) => previousConnection.filter((_, currentIndex) => currentIndex !== index));

  useEffect(() => {
    if (!apiKey) return;
    fetch(`${API_BASE}/logosdb/get_models`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
      body: JSON.stringify({ logos_key: apiKey }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (Array.isArray(data)) setModels(data);
      })
      .catch(() => {});
  }, [apiKey]);

  const handleSubmit = async () => {
    if (!apiKey) return;
    if (!name || !baseUrl || !providerType) {
      setStatusMessage("Name, Base URL, and Provider Type are required.");
      return;
    }

    const payload = {
      provider_name: name,
      base_url: baseUrl,
      api_key: providerKey,
      auth_name: authName,
      auth_format: authFormat,
      provider_type: providerType,
      cloud_provider_type:
        cloudProviderType === "none" ? null : cloudProviderType,
      privacy_level: privacy,
      logos_key: apiKey,
    };

    try {
      setSubmitting(true);
      setStatusMessage(null);
      const res = await fetch(`${API_BASE}/logosdb/add_provider`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${apiKey}`,
        },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        const result = await res.json();
        const body = Array.isArray(result) ? result[0] : result;
        const providerId = body?.["provider-id"];

        if (providerId) {
          for (const conn of connections.filter((c) => c.modelId)) {
            await fetch(`${API_BASE}/logosdb/connect_model_provider`, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${apiKey}`,
              },
              body: JSON.stringify({
                logos_key: apiKey,
                provider_id: providerId,
                model_id: parseInt(conn.modelId, 10),
                endpoint: conn.endpoint || null,
                api_key: conn.apiKey || null,
              }),
            });
          }
        }

        setStatusMessage("Provider added successfully.");
        setName("");
        setBaseUrl("");
        setProviderKey("");
        setAuthName("");
        setAuthFormat("");
        setProviderType("cloud");
        setCloudProviderType("none");
        setPrivacy("LOCAL");
        setConnections([]);
        router.push("/providers");
      } else {
        setStatusMessage("Could not add the provider. Please try again.");
      }
    } catch (e) {
      setStatusMessage("Unexpected error while adding the provider.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <VStack className="w-full space-y-6">
      <VStack className="space-y-1">
        <Text
          size="2xl"
          className="text-center font-bold text-black dark:text-white"
        >
          Add Provider
        </Text>
        <Text className="text-center text-gray-500 dark:text-gray-300">
          Register a new provider connection
        </Text>
      </VStack>

      <Box className="space-y-6 rounded-2xl border border-outline-200 bg-secondary-200 p-6">
        <HStack className="flex-col gap-6 md:flex-row">
          <VStack className="flex-1 space-y-4">
            <Field
              label="Provider Name"
              value={name}
              onChangeText={setName}
              placeholder="Azure OpenAI / Local Worker"
            />
            <Field
              label="Base URL"
              value={baseUrl}
              onChangeText={setBaseUrl}
              placeholder="https://api.example.com"
            />
            <Field
              label="API Key"
              value={providerKey}
              onChangeText={setProviderKey}
              placeholder="sk-..."
            />
            <HStack space="md">
              <Box className="flex-1">
                <Field
                  label="Auth Header Name"
                  value={authName}
                  onChangeText={setAuthName}
                  placeholder="Authorization"
                />
              </Box>
              <Box className="flex-1">
                <Field
                  label="Auth Format"
                  value={authFormat}
                  onChangeText={setAuthFormat}
                  placeholder="Bearer {}"
                />
              </Box>
            </HStack>
          </VStack>

          <VStack className="flex-1 space-y-4">
            <Box className="space-y-2">
              <Text className="text-sm font-semibold text-black dark:text-white">
                Provider Type
              </Text>
              <Select
                selectedValue={providerType}
                onValueChange={(val) => setProviderType(val || "cloud")}
              >
                <SelectTrigger className="rounded-md border border-outline-200 bg-white px-3 py-2 dark:border-outline-700 dark:bg-[#1b1b1b]">
                  <SelectInput
                    placeholder="Select type"
                    value={providerType}
                    className="text-black dark:text-white"
                  />
                </SelectTrigger>
                <SelectPortal>
                  <SelectBackdrop />
                  <SelectContent className="border border-outline-200 bg-white dark:border-outline-700 dark:bg-[#111]">
                    {providerTypeOptions.map((opt) => (
                      <SelectItem key={opt} label={opt} value={opt} />
                    ))}
                  </SelectContent>
                </SelectPortal>
              </Select>
            </Box>

            <Box className="space-y-2">
              <Text className="text-sm font-semibold text-black dark:text-white">
                Cloud Provider Type (Optional)
              </Text>
              <Select
                selectedValue={cloudProviderType}
                onValueChange={(val) => setCloudProviderType(val || "none")}
              >
                <SelectTrigger className="rounded-md border border-outline-200 bg-white px-3 py-2 dark:border-outline-700 dark:bg-[#1b1b1b]">
                  <SelectInput
                    placeholder="Select cloud provider"
                    value={cloudProviderType}
                    className="text-black dark:text-white"
                  />
                </SelectTrigger>
                <SelectPortal>
                  <SelectBackdrop />
                  <SelectContent className="border border-outline-200 bg-white dark:border-outline-700 dark:bg-[#111]">
                    {cloudProviderTypeOptions.map((opt) => (
                      <SelectItem key={opt} label={opt} value={opt} />
                    ))}
                  </SelectContent>
                </SelectPortal>
              </Select>
            </Box>

            <Box className="space-y-2">
              <Text className="text-sm font-semibold text-black dark:text-white">
                Privacy Level
              </Text>
              <Select
                selectedValue={privacy}
                onValueChange={(val) => setPrivacy(val || "LOCAL")}
              >
                <SelectTrigger className="rounded-md border border-outline-200 bg-white px-3 py-2 dark:border-outline-700 dark:bg-[#1b1b1b]">
                  <SelectInput
                    placeholder="Select privacy"
                    value={privacy}
                    className="text-black dark:text-white"
                  />
                </SelectTrigger>
                <SelectPortal>
                  <SelectBackdrop />
                  <SelectContent className="border border-outline-200 bg-white dark:border-outline-700 dark:bg-[#111]">
                    {privacyOptions.map((opt) => (
                      <SelectItem key={opt} label={opt} value={opt} />
                    ))}
                  </SelectContent>
                </SelectPortal>
              </Select>
            </Box>
          </VStack>
        </HStack>

        <VStack space="md" className="w-full">
          {connections.map((conn, i) => (
            <HStack key={i} className="w-full items-end gap-3">
              <Box className="flex-1 space-y-2">
                <Text className="text-sm font-semibold text-black dark:text-white">
                  Model
                </Text>
                <ModelPicker
                  models={models}
                  selectedId={conn.modelId}
                  onSelect={(val) => updateConn(i, "modelId", val)}
                  excludedIds={connections
                    .filter((_, idx) => idx !== i)
                    .map((c) => c.modelId)
                    .filter(Boolean)}
                  placeholder="None"
                />
              </Box>

              <Box className="flex-1">
                <Field
                  label="Endpoint"
                  value={conn.endpoint}
                  onChangeText={(val) => updateConn(i, "endpoint", val)}
                  placeholder="https://..."
                />
              </Box>

              <Box className="flex-1">
                <Field
                  label="API Key"
                  value={conn.apiKey}
                  onChangeText={(val) => updateConn(i, "apiKey", val)}
                  placeholder="sk-..."
                />
              </Box>

              <Pressable
                onPress={() => removeConn(i)}
                className="mb-1 rounded-md p-3"
              >
                <Icon as={TrashIcon} size="md" />
              </Pressable>
            </HStack>
          ))}

          <Button
            size="md"
            className="mt-2 self-start bg-black dark:bg-white"
            onPress={addConn}
          >
            <ButtonText className="text-white dark:text-black">
              + Connect Model
            </ButtonText>
          </Button>
        </VStack>

        <HStack className="mt-4 w-full flex-wrap items-center justify-between gap-3">
          {statusMessage ? (
            <Text className="text-sm text-gray-700 dark:text-gray-300">
              {statusMessage}
            </Text>
          ) : (
            <Box />
          )}

          <HStack className="ml-auto gap-3">
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
              onPress={() => router.push("/providers")}
            >
              <ButtonText>Cancel</ButtonText>
            </Button>
          </HStack>
        </HStack>
      </Box>
    </VStack>
  );
}

const Field = ({
  label,
  helper,
  value,
  onChangeText,
  placeholder,
}: FieldProps) => {
  return (
    <Box className="space-y-2">
      <Text className="text-sm font-semibold text-black dark:text-white">
        {label}
      </Text>
      <Input className="border border-outline-200 bg-white dark:border-outline-700 dark:bg-[#1b1b1b]">
        <InputField
          value={value}
          onChangeText={onChangeText}
          placeholder={placeholder}
          className="text-black placeholder:text-gray-500 dark:text-white dark:placeholder:text-gray-400"
        />
      </Input>
      {helper && (
        <Text className="text-xs text-gray-500 dark:text-gray-400">
          {helper}
        </Text>
      )}
    </Box>
  );
};
