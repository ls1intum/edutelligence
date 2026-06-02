import React, { useState } from "react";
import { Modal, Pressable, ScrollView, View, ActivityIndicator, Platform } from "react-native";
import {API_BASE, ImportRow, STATUS_COLORS} from "@/components/statistics/constants";
import { OVERLAY, CARD } from "./base-modal";
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Button, ButtonText } from "@/components/ui/button";
import { Table, TableHeader, TableBody, TableHead, TableRow, TableData } from "@/components/ui/table";

type ImportResult = {
    summary: { created: number; existing: number; failed: number };
    rows: ImportRow[];
};

type Props = {
    visible: boolean;
    onClose: () => void;
    apiKey: string;
    onImported?: () => void;
};

export function CsvImportModal({ visible, onClose, apiKey, onImported }: Props) {
    const [fileName, setFileName] = useState<string | null>(null);
    const [fileData, setFileData] = useState<File | null>(null);
    const [uploading, setUploading] = useState(false);
    const [result, setResult] = useState<ImportResult | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [copied, setCopied] = useState(false);

    const reset = () => {
        setFileName(null);
        setFileData(null);
        setUploading(false);
        setResult(null);
        setError(null);
        setCopied(false);
    };

    const handleClose = () => {
        if (uploading) return;
        reset();
        onClose();
    };

    const pickFile = () => {
        if (Platform.OS !== "web") return;
        const input = document.createElement("input");
        input.type = "file";
        input.accept = ".csv";
        input.click();
        input.onchange = (e: Event) => {
            const f = (e.target as HTMLInputElement).files?.[0];
            if (f) {
                setFileName(f.name);
                setFileData(f);
                setResult(null);
                setError(null);
            }
        };
    };

    const upload = async () => {
        if (!fileData) return;
        setUploading(true);
        setError(null);
        try {
            const form = new FormData();
            form.append("file", fileData);
            const res = await fetch(`${API_BASE}/users/import`, {
                method: "POST",
                headers: { "logos-key": apiKey },
                body: form,
            });
            const data = await res.json();
            if (!res.ok) {
                setError(data.detail || "Import failed.");
            } else {
                setResult(data as ImportResult);
                onImported?.();
            }
        } catch {
            setError("Connection failed. Please try again.");
        } finally {
            setUploading(false);
        }
    };

    const escapeCsvValue = (value: unknown) => {
        const str = String(value ?? "");
        if (/[",\n\r]/.test(str)) {
            return `"${str.replace(/"/g, '""')}"`;
        }
        return str;
    };

    const buildCredentialsCsv = () => {
        if (!result) return "";
        const header = ["email", "username", "apiKey", "team", "status"];
        const rows = result.rows.map(r =>
            [
                r.email,
                r.username,
                r.apiKey,
                r.team,
                r.status,
            ].map(escapeCsvValue).join(",")
        );
        return [header.join(","), ...rows].join("\n");
    };

    const copyCredentials = async () => {
        if (!result) return;
        const csv = buildCredentialsCsv();
        if (Platform.OS === "web") {
            await navigator.clipboard.writeText(csv);
        }
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };

    const downloadCsv = () => {
        if (!result || Platform.OS !== "web") return;
        const content = buildCredentialsCsv();
        const blob = new Blob([content], { type: "text/csv" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "import-credentials.csv";
        a.click();
        URL.revokeObjectURL(url);
    };

    return (
        <Modal visible={visible} transparent onRequestClose={uploading ? undefined : handleClose}>
            <Pressable style={OVERLAY} onPress={uploading ? undefined : handleClose}>
                <Pressable
                    style={[CARD, { maxWidth: 700, width: "100%", maxHeight: "85%" }]}
                    onPress={e => e.stopPropagation?.()}
                >
                    <ScrollView>
                        <VStack space="md">
                            <Text style={{ fontWeight: "700", fontSize: 18 }}>Import Users from CSV</Text>

                            {!result && (
                                <>
                                    <Text style={{ fontSize: 13, color: "#555" }}>
                                        Required columns: prename, name, email, team
                                    </Text>
                                    <HStack space="sm" style={{ alignItems: "center" }}>
                                        <Button variant="outline" onPress={pickFile} disabled={uploading}>
                                            <ButtonText>Choose File</ButtonText>
                                        </Button>
                                        <Text style={{ fontSize: 13, color: fileName ? "#333" : "#aaa" }}>
                                            {fileName ?? "No file selected"}
                                        </Text>
                                    </HStack>
                                    {error && (
                                        <Text style={{ color: "#E63535", fontSize: 12 }}>{error}</Text>
                                    )}
                                    {uploading && (
                                        <HStack space="sm" style={{ alignItems: "center" }}>
                                            <ActivityIndicator size="small" color="#006DFF" />
                                            <Text style={{ fontSize: 13, color: "#555" }}>Importing...</Text>
                                        </HStack>
                                    )}
                                    <HStack space="md" className="justify-end mt-2">
                                        <Button variant="outline" onPress={handleClose} disabled={uploading}>
                                            <ButtonText>Cancel</ButtonText>
                                        </Button>
                                        <Button
                                            onPress={upload}
                                            disabled={!fileData || uploading}
                                            style={{ opacity: (!fileData || uploading) ? 0.5 : 1 }}
                                        >
                                            <ButtonText>Upload</ButtonText>
                                        </Button>
                                    </HStack>
                                </>
                            )}

                            {result && (
                                <VStack
                                    space="md"
                                    style={{
                                        maxHeight: 520,
                                        width: "100%",
                                    }}
                                >
                                    <HStack space="lg" className="flex-wrap">
                                        <Text style={{ fontSize: 13, color: STATUS_COLORS.created }}>
                                            Created: {result.summary.created}
                                        </Text>
                                        <Text style={{ fontSize: 13, color: STATUS_COLORS.existing }}>
                                            Existing: {result.summary.existing}
                                        </Text>
                                        <Text style={{ fontSize: 13, color: STATUS_COLORS.failed }}>
                                            Failed: {result.summary.failed}
                                        </Text>
                                    </HStack>

                                    <Box
                                        className="w-full overflow-hidden rounded-lg border border-outline-200 bg-secondary-200"
                                        style={{
                                            flex: 1,
                                            minHeight: 180,
                                            maxHeight: 360,
                                        }}
                                    >
                                        <ScrollView horizontal showsHorizontalScrollIndicator>
                                            <ScrollView showsVerticalScrollIndicator>
                                                <Box style={{ minWidth: 980 }}>
                                                    <Table className="w-full">
                                                        <TableHeader>
                                                            <TableRow className="bg-secondary-200">
                                                                <TableHead style={{ width: 220 }}>Email</TableHead>
                                                                <TableHead style={{ width: 140 }}>Username</TableHead>
                                                                <TableHead style={{ width: 300 }}>API Key</TableHead>
                                                                <TableHead style={{ width: 140 }}>Team</TableHead>
                                                                <TableHead style={{ width: 120 }}>Status</TableHead>
                                                                <TableHead style={{ width: 220 }}>Error</TableHead>
                                                            </TableRow>
                                                        </TableHeader>

                                                        <TableBody>
                                                            {result.rows.map((row, i) => (
                                                                <TableRow key={i} className="bg-secondary-200">
                                                                    <TableData style={{ width: 220 }}>
                                                                        <Text style={{ fontSize: 12 }}>
                                                                            {row.email ?? "-"}
                                                                        </Text>
                                                                    </TableData>

                                                                    <TableData style={{ width: 140 }}>
                                                                        <Text style={{ fontSize: 12 }}>
                                                                            {row.username ?? "-"}
                                                                        </Text>
                                                                    </TableData>

                                                                    <TableData style={{ width: 300 }}>
                                                                        <Text style={{ fontSize: 12 }}>
                                                                            {row.apiKey ?? "-"}
                                                                        </Text>
                                                                    </TableData>

                                                                    <TableData style={{ width: 140 }}>
                                                                        <Text style={{ fontSize: 12 }}>
                                                                            {row.team ?? "-"}
                                                                        </Text>
                                                                    </TableData>

                                                                    <TableData style={{ width: 120 }}>
                                                                        <View style={{
                                                                            borderRadius: 8,
                                                                            paddingHorizontal: 8,
                                                                            paddingVertical: 4,
                                                                            borderWidth: 1,
                                                                            borderColor: STATUS_COLORS[row.status],
                                                                        }}>
                                                                            <Text
                                                                                style={{
                                                                                    fontSize: 12,
                                                                                    color: STATUS_COLORS[row.status],
                                                                                    fontWeight: "600",
                                                                                }}
                                                                            >
                                                                                {row.status}
                                                                            </Text>
                                                                        </View>
                                                                    </TableData>

                                                                    <TableData style={{ width: 220 }}>
                                                                        <Text
                                                                            ellipsizeMode="tail"
                                                                            style={{
                                                                                fontSize: 11,
                                                                                color: "#E63535",
                                                                            }}
                                                                        >
                                                                            {row.error ?? ""}
                                                                        </Text>
                                                                    </TableData>
                                                                </TableRow>
                                                            ))}
                                                        </TableBody>
                                                    </Table>
                                                </Box>
                                            </ScrollView>
                                        </ScrollView>
                                    </Box>

                                    <View
                                        style={{
                                            borderTopWidth: 1,
                                            borderColor: "#e2e8f0",
                                            paddingTop: 14,
                                            paddingBottom: 10,
                                            backgroundColor: "white",
                                        }}
                                    >
                                        <HStack space="md" className="justify-end flex-wrap">
                                            <Button
                                                variant="outline"
                                                onPress={copyCredentials}
                                                disabled={result.summary.created === 0}
                                                style={{
                                                    opacity: result.summary.created === 0 ? 0.5 : 1,
                                                }}
                                            >
                                                <ButtonText>
                                                    {copied ? "Copied!" : "Copy Credentials"}
                                                </ButtonText>
                                            </Button>

                                            <Button variant="outline" onPress={downloadCsv}>
                                                <ButtonText>Download CSV</ButtonText>
                                            </Button>

                                            <Button onPress={handleClose}>
                                                <ButtonText>Done</ButtonText>
                                            </Button>
                                        </HStack>
                                    </View>
                                </VStack>
                            )}
                        </VStack>
                    </ScrollView>
                </Pressable>
            </Pressable>
        </Modal>
    );
}
