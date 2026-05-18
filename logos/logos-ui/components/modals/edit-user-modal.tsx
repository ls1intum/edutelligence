import React, { useState, useEffect } from "react";
import { Modal, Pressable } from "react-native";
import { API_BASE } from "@/components/statistics/constants";
import { OVERLAY, CARD } from "./base-modal";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Button, ButtonText } from "@/components/ui/button";
import { Input, InputField } from "@/components/ui/input";

type Props = {
  visible: boolean;
  onClose: () => void;
  onSaved: (updatedUser: any) => void;
  apiKey: string;
  user: any | null;
};

export function EditUserModal({
  visible,
  onClose,
  onSaved,
  apiKey,
  user,
}: Props) {
  const [form, setForm] = useState({ prename: "", name: "", email: "" });
  const [loading, setLoading] = useState(false);

  const [error, setError] = useState("");

  useEffect(() => {
    if (user && visible) {
      setForm({
        prename: user.prename || "",
        name: user.name || "",
        email: user.email || "",
      });
      setError("");
    }
  }, [user, visible]);

  const isAnyFieldEmpty =
    !form.prename.trim() || !form.name.trim() || !form.email.trim();

  const handleSave = async () => {
    setError("");

    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
      setError("Email not valid.");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/users/${user.id}`, {
        method: "PATCH",
        headers: { "logos-key": apiKey, "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });

      const data = await res.json();

      if (res.ok) {
        onSaved({ ...user, ...form });
        onClose();
      } else {
        let errorMsg =
          "Email already in use.";

        if (data.error) {
          if (typeof data.error === "string") {
            errorMsg = data.error;
          } else if (typeof data.error === "object" && data.error.message) {
            errorMsg = data.error.message;
          }
        } else if (typeof data.detail === "string") {
          errorMsg = data.detail;
        }

        setError(errorMsg);
      }
    } catch {
      setError("Connection error.");
    } finally {
      setLoading(false);
    }
  };

  if (!user) return null;

  return (
    <Modal visible={visible} transparent onRequestClose={onClose}>
      <Pressable style={OVERLAY} onPress={onClose}>
        <Pressable
          style={[CARD, { maxWidth: 380, width: "100%" }]}
          onPress={(e) => e.stopPropagation?.()}
        >
          <VStack space="md">
            <Text style={{ fontWeight: "700", fontSize: 18 }}>
              Edit User
            </Text>

            <VStack space="sm">
              <Text style={{ fontSize: 13, fontWeight: "600", color: "#555" }}>
                Prename
              </Text>
              <Input>
                <InputField
                  placeholder="prename"
                  value={form.prename}
                  onChangeText={(v) => setForm((f) => ({ ...f, prename: v }))}
                />
              </Input>
            </VStack>

            <VStack space="sm">
              <Text style={{ fontSize: 13, fontWeight: "600", color: "#555" }}>
                Name
              </Text>
              <Input>
                <InputField
                  placeholder="name"
                  value={form.name}
                  onChangeText={(v) => setForm((f) => ({ ...f, name: v }))}
                />
              </Input>
            </VStack>

            <VStack space="sm">
              <Text style={{ fontSize: 13, fontWeight: "600", color: "#555" }}>
                E-Mail
              </Text>
              <Input>
                <InputField
                  placeholder="E-Mail"
                  value={form.email}
                  autoCapitalize="none"
                  keyboardType="email-address"
                  onChangeText={(v) => setForm((f) => ({ ...f, email: v }))}
                />
              </Input>
            </VStack>

            {error ? (
              <Text
                style={{
                  color: "#e63535",
                  fontSize: 12,
                  fontWeight: "500",
                  marginTop: 4,
                }}
              >
                {error}
              </Text>
            ) : null}

            <HStack space="md" className="mt-4 justify-end">
              <Button variant="outline" onPress={onClose}>
                <ButtonText>Cancel</ButtonText>
              </Button>
              <Button
                onPress={handleSave}
                disabled={isAnyFieldEmpty || loading}
                style={{ opacity: isAnyFieldEmpty || loading ? 0.5 : 1 }}
              >
                <ButtonText>
                  {loading ? "Saving..." : "Save"}
                </ButtonText>
              </Button>
            </HStack>
          </VStack>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
