import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ActivityIndicator, Animated, Easing, View } from "react-native";

import { Text } from "@/components/ui/text";
import { HStack } from "@/components/ui/hstack";
import { VStack } from "@/components/ui/vstack";
import { Button, ButtonText } from "@/components/ui/button";
import type { RequestItem } from "@/components/statistics/request-stack";
import type { PaginatedRequestItem, PaginatedRequestResponse } from "@/components/statistics/types";
import { API_BASE } from "@/components/statistics/constants";

/* ── helpers (mirrored from request-stack.tsx) ── */

export type RequestStage = "queued" | "executing" | "complete";

function deriveStage(item: PaginatedRequestItem): RequestStage {
  if (item.request_complete_ts) return "complete";
  if (item.scheduled_ts) return "executing";
  return "queued";
}

function getBorderColor(stage: RequestStage, status: string): string {
  if (stage === "queued") return "#8B5CF6";
  if (stage === "executing") return "#3B82F6";
  switch (status.toLowerCase()) {
    case "success": return "#10B981";
    case "error":   return "#EF4444";
    case "timeout": return "#F59E0B";
    default:        return "#64748B";
  }
}

function withAlpha(hex: string, alphaHex: string): string {
  return `${hex}${alphaHex}`;
}

function formatTimeAgo(ts: string | null, nowMs: number): string {
  if (!ts) return "";
  const diffS = Math.max(0, (nowMs - new Date(ts).getTime()) / 1000);
  if (diffS < 60) return `${Math.round(diffS)}s ago`;
  const diffM = diffS / 60;
  if (diffM < 60) return `${Math.round(diffM)}m ago`;
  const diffH = diffM / 60;
  if (diffH < 24) return `${Math.round(diffH)}h ago`;
  return `${Math.round(diffH / 24)}d ago`;
}

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}m ${s}s`;
}

/* ── individual card ── */

function PaginatedRequestCard({ item }: { item: PaginatedRequestItem }) {
  const stage = deriveStage(item);
  const borderColor = getBorderColor(stage, item.status);
  const borderTint = withAlpha(borderColor, "0D");

  const borderPulse = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (stage !== "complete") {
      const loop = Animated.loop(
        Animated.sequence([
          Animated.timing(borderPulse, { toValue: 1, duration: 1100, useNativeDriver: true }),
          Animated.timing(borderPulse, { toValue: 0, duration: 1100, useNativeDriver: true }),
        ])
      );
      loop.start();
      return () => loop.stop();
    } else {
      borderPulse.setValue(0);
    }
  }, [stage]);

  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const interval = stage === "complete" ? 10000 : 1000;
    const id = setInterval(() => setNow(Date.now()), interval);
    return () => clearInterval(id);
  }, [stage]);

  const timeAgo = formatTimeAgo(item.enqueue_ts || item.timestamp, now);
  const isCold = item.cold_start === true;

  const totalTimeLabel = (): string => {
    if (stage === "complete" && item.total_seconds != null) {
      return `${item.total_seconds.toFixed(2)}s`;
    }
    if (item.enqueue_ts) {
      return formatElapsed((now - new Date(item.enqueue_ts).getTime()) / 1000);
    }
    return "...";
  };

  const renderStageBadge = () => {
    if (stage === "queued") {
      return (
        <View className="rounded-md bg-purple-500/10 px-2 py-0.5">
          <Text className="text-xs font-semibold text-purple-500">QUEUED</Text>
        </View>
      );
    }
    if (stage === "executing") {
      const elapsed = item.scheduled_ts
        ? (now - new Date(item.scheduled_ts).getTime()) / 1000
        : 0;
      return (
        <HStack className="items-center gap-2">
          <View className="rounded-md bg-blue-500/10 px-2 py-0.5">
            <Text className="text-xs font-semibold text-blue-500">RUNNING</Text>
          </View>
          <Text className="text-sm font-medium text-typography-700 ">
            {formatElapsed(elapsed)}
          </Text>
        </HStack>
      );
    }
    return null;
  };

  return (
    <View className="mb-1.5">
      <Animated.View
        style={{ borderWidth: 2, borderColor, borderRadius: 10, backgroundColor: borderTint }}
      >
        {stage !== "complete" && (
          <Animated.View
            pointerEvents="none"
            style={{
              position: "absolute",
              inset: 0,
              borderWidth: 2,
              borderColor,
              borderRadius: 10,
              opacity: borderPulse.interpolate({ inputRange: [0, 1], outputRange: [0.2, 0.6] }),
            }}
          />
        )}
        <HStack className="w-full items-center px-3 py-2.5" space="md">
          {/* Left */}
          <VStack className="min-w-0 flex-1">
            <HStack className="items-center gap-2">
              <Text className="text-base font-medium text-typography-900 " numberOfLines={1}>
                {item.model_name}
              </Text>
              <Text className="text-xs text-typography-400">{timeAgo}</Text>
            </HStack>
            <HStack className="items-center gap-2">
              <Text className="text-sm text-typography-400" numberOfLines={1}>
                {item.provider_name}
              </Text>
              {/* Cloud / Local badge */}
              <View
                className={`rounded-full px-1.5 py-0.5 ${item.is_cloud ? "bg-cyan-500/10" : "bg-orange-500/10"}`}
              >
                <Text className={`text-xs font-medium ${item.is_cloud ? "text-cyan-500" : "text-orange-400"}`}>
                  {item.is_cloud ? "CLOUD" : "LOCAL"}
                </Text>
              </View>
            </HStack>
            {stage === "complete" && item.status === "error" && item.error_message && (
              <Text className="text-xs text-red-500" numberOfLines={1}>
                {item.error_message.length > 60
                  ? item.error_message.slice(0, 60) + "..."
                  : item.error_message}
              </Text>
            )}
          </VStack>

          {/* Right */}
          <VStack className="shrink-0 items-end gap-1">
            {renderStageBadge()}
            {stage === "complete" && (
              <HStack className="items-center gap-1.5">
                {!item.is_cloud && (
                  <View className={`rounded-md px-1.5 py-0.5 ${isCold ? "bg-sky-600/15" : "bg-orange-600/15"}`}>
                    <Text className={`text-xs font-semibold ${isCold ? "text-sky-400" : "text-orange-400"}`}>
                      {isCold ? "COLD" : "HOT"}
                    </Text>
                  </View>
                )}
                <Text className="text-base font-semibold text-typography-900 ">
                  {totalTimeLabel()}
                </Text>
              </HStack>
            )}
            {stage === "complete" && item.queue_seconds != null && item.duration != null && (
              <Text className="text-xs text-typography-400">
                Queue: {item.queue_seconds.toFixed(1)}s | Exec: {item.duration.toFixed(1)}s
              </Text>
            )}
          </VStack>
        </HStack>
      </Animated.View>
    </View>
  );
}

/* ── helper: merge WS live items with paginated items ── */

function mergeWithLive(
  liveRequests: RequestItem[],
  pageItems: PaginatedRequestItem[],
  perPage: number
): PaginatedRequestItem[] {
  const pageIds = new Set(pageItems.map((r) => r.request_id));

  // Convert WS RequestItem to PaginatedRequestItem shape
  const liveConverted: PaginatedRequestItem[] = liveRequests
    .filter((r) => !pageIds.has(r.request_id))
    .map((r) => ({
      request_id: r.request_id,
      model_name: r.model_name,
      provider_name: r.provider_name,
      // infer is_cloud from provider name (fallback when paginated endpoint not reached)
      is_cloud:
        r.provider_name?.toLowerCase().includes("openai") ||
        r.provider_name?.toLowerCase().includes("azure") ||
        r.provider_name?.toLowerCase().includes("cloud"),
      status: r.status,
      timestamp: r.timestamp,
      duration: r.duration,
      cold_start: r.cold_start,
      enqueue_ts: r.enqueue_ts,
      scheduled_ts: r.scheduled_ts,
      request_complete_ts: r.request_complete_ts,
      queue_seconds: r.queue_seconds,
      total_seconds: r.total_seconds,
      initial_priority: r.initial_priority,
      priority_when_scheduled: r.priority_when_scheduled,
      queue_depth_at_enqueue: r.queue_depth_at_enqueue,
      error_message: r.error_message,
    }));

  return [...liveConverted, ...pageItems]
    .sort((a, b) => {
      const aTs = a.enqueue_ts ?? a.timestamp ?? "";
      const bTs = b.enqueue_ts ?? b.timestamp ?? "";
      return bTs.localeCompare(aTs);
    })
    .slice(0, perPage);
}

/* ── main component ── */

async function fetchPage(
  apiKey: string,
  page: number,
  perPage = 20
): Promise<PaginatedRequestResponse> {
  const resp = await fetch(`${API_BASE}/logosdb/paginated_requests`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      logos_key: apiKey,
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({ page, per_page: perPage }),
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

const PER_PAGE = 7;

type PaginatedRequestListProps = {
  liveRequests: RequestItem[];
  apiKey: string | null;
  nowMs: number;
};

export default function PaginatedRequestList({
  liveRequests,
  apiKey,
  nowMs,
}: PaginatedRequestListProps) {
  const [page, setPage] = useState(1);
  const [pageData, setPageData] = useState<PaginatedRequestResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const load = useCallback(
    async (targetPage: number) => {
      if (!apiKey) return;
      setLoading(true);
      setFetchError(null);
      try {
        const data = await fetchPage(apiKey, targetPage, PER_PAGE);
        if (mountedRef.current) {
          setPageData(data);
          setPage(targetPage);
        }
      } catch (e: any) {
        if (mountedRef.current) {
          setFetchError(e?.message ?? "Failed to load requests");
        }
      } finally {
        if (mountedRef.current) setLoading(false);
      }
    },
    [apiKey]
  );

  // Initial load
  useEffect(() => {
    load(1);
  }, [load]);

  // Refresh page 1 when live requests update (new items arrived)
  const liveCountRef = useRef(liveRequests.length);
  useEffect(() => {
    if (page === 1 && liveRequests.length !== liveCountRef.current) {
      liveCountRef.current = liveRequests.length;
      // Silently refresh page 1 in the background to get accurate totals
      if (apiKey) {
        fetchPage(apiKey, 1, PER_PAGE)
          .then((data) => { if (mountedRef.current && page === 1) setPageData(data); })
          .catch(() => {});
      }
    }
  }, [liveRequests.length, page, apiKey]);

  const displayItems = useMemo((): PaginatedRequestItem[] => {
    if (!pageData) return [];
    if (page === 1) {
      return mergeWithLive(liveRequests, pageData.requests, PER_PAGE);
    }
    return pageData.requests;
  }, [pageData, page, liveRequests]);

  const totalPages = pageData?.total_pages ?? 1;
  const total = pageData?.total ?? 0;

  return (
    <VStack className="w-full py-2">
      {/* Header */}
      <HStack className="mb-2 items-center justify-between">
        <Text className="text-lg font-bold text-typography-900 ">
          Requests
        </Text>
        {total > 0 && (
          <Text className="text-sm text-typography-400">{total} total</Text>
        )}
      </HStack>

      {/* Error */}
      {fetchError && (
        <View className="mb-2 rounded-xl border border-red-500/30 bg-red-500/10 p-3">
          <Text className="text-sm text-red-500">{fetchError}</Text>
          <Button
            size="sm"
            variant="link"
            onPress={() => load(page)}
            className="mt-1 self-start"
          >
            <ButtonText className="text-red-400">Retry</ButtonText>
          </Button>
        </View>
      )}

      {/* List */}
      {loading && !pageData ? (
        <View className="items-center justify-center py-8">
          <ActivityIndicator size="small" color="#006DFF" />
        </View>
      ) : displayItems.length === 0 ? (
        <View className="items-center py-8">
          <Text className="text-sm text-typography-400">No requests yet.</Text>
        </View>
      ) : (
        <View className="w-full">
          {displayItems.map((req) => (
            <PaginatedRequestCard key={req.request_id} item={req} />
          ))}
        </View>
      )}

      {/* Pagination controls */}
      {totalPages > 1 && (
        <HStack className="mt-3 items-center justify-between">
          <Button
            size="sm"
            variant="outline"
            isDisabled={page <= 1 || loading}
            onPress={() => load(page - 1)}
            className="rounded-lg border-outline-200 "
          >
            <ButtonText className="text-typography-700 ">← Prev</ButtonText>
          </Button>

          <VStack className="items-center">
            <Text className="text-sm text-typography-600 ">
              Page {page} of {totalPages}
            </Text>
            {loading && (
              <ActivityIndicator size="small" color="#006DFF" style={{ marginTop: 2 }} />
            )}
          </VStack>

          <Button
            size="sm"
            variant="outline"
            isDisabled={page >= totalPages || loading}
            onPress={() => load(page + 1)}
            className="rounded-lg border-outline-200 "
          >
            <ButtonText className="text-typography-700 ">Next →</ButtonText>
          </Button>
        </HStack>
      )}
    </VStack>
  );
}
