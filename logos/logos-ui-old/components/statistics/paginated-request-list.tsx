import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ActivityIndicator, Animated, View } from "react-native";

import { Text } from "@/components/ui/text";
import { HStack } from "@/components/ui/hstack";
import { VStack } from "@/components/ui/vstack";
import { Button, ButtonText } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { RequestItem } from "@/components/statistics/request-stack";
import type { PaginatedRequestItem, PaginatedRequestResponse } from "@/components/statistics/types";
import { API_BASE } from "@/components/statistics/constants";

/**
 * Row-shaped skeleton placeholder shown while the initial paginated
 * page is in flight. Mirrors the real row layout (colored border,
 * model/provider on the left, total time + meta on the right) so the
 * card keeps its size and the user can tell what's coming.
 */
function RequestRowSkeleton() {
  const widths = [
    { name: 220, age: 56, total: 64, meta: 200 },
    { name: 250, age: 48, total: 70, meta: 220 },
    { name: 195, age: 60, total: 58, meta: 180 },
    { name: 235, age: 52, total: 66, meta: 208 },
    { name: 210, age: 56, total: 60, meta: 196 },
  ];
  return (
    <View style={{ width: "100%" }}>
      {widths.map((w, i) => (
        <View key={i} style={{ marginBottom: 8 }}>
          <View
            style={{
              width: "100%",
              borderWidth: 2,
              borderColor: "rgba(15,23,42,0.08)",
              borderRadius: 12,
              backgroundColor: "rgba(15,23,42,0.02)",
              paddingTop: 9,
              paddingBottom: 9,
              paddingLeft: 15,
              paddingRight: 15,
              flexDirection: "row",
              alignItems: "center",
              columnGap: 16,
            }}
          >
            <View style={{ flexGrow: 1, flexShrink: 1, minWidth: 0, rowGap: 6 }}>
              <View style={{ flexDirection: "row", alignItems: "center", columnGap: 8 }}>
                <Skeleton variant="rounded" startColor="bg-background-200" style={{ width: w.name, height: 14, borderRadius: 6 }} />
                <Skeleton variant="rounded" startColor="bg-background-200" style={{ width: w.age, height: 10, borderRadius: 3 }} />
              </View>
              <View style={{ flexDirection: "row", alignItems: "center", columnGap: 8 }}>
                <Skeleton variant="rounded" startColor="bg-background-200" style={{ width: 92, height: 10, borderRadius: 3 }} />
                <Skeleton variant="rounded" startColor="bg-background-200" style={{ width: 42, height: 14, borderRadius: 4 }} />
              </View>
            </View>
            <View style={{ alignItems: "flex-end", rowGap: 6 }}>
              <View style={{ flexDirection: "row", alignItems: "center", columnGap: 6 }}>
                <Skeleton variant="rounded" startColor="bg-background-200" style={{ width: 36, height: 14, borderRadius: 4 }} />
                <Skeleton variant="rounded" startColor="bg-background-200" style={{ width: w.total, height: 16, borderRadius: 6 }} />
              </View>
              <Skeleton variant="rounded" startColor="bg-background-200" style={{ width: w.meta, height: 10, borderRadius: 3 }} />
            </View>
          </View>
        </View>
      ))}
    </View>
  );
}

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

type CardProps = {
  item: PaginatedRequestItem;
  /** Shared ticker from the parent list — avoids one setInterval per card. */
  now: number;
};

const PaginatedRequestCard = React.memo(function PaginatedRequestCard({ item, now }: CardProps) {
  const stage = deriveStage(item);
  const borderColor = getBorderColor(stage, item.status);
  // Live rows: full-strength border. Completed rows: keep them visibly
  // coloured (~80% alpha) plus a stronger stage-tinted fill so the row
  // reads as a clearly stage-coloured surface, not "barely a hairline".
  const restingBorder = stage === "complete" ? withAlpha(borderColor, "cc") : borderColor;
  const tint = withAlpha(borderColor, "1a");

  const borderPulse = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (stage !== "complete") {
      const loop = Animated.loop(
        Animated.sequence([
          Animated.timing(borderPulse, { toValue: 1, duration: 1000, useNativeDriver: true }),
          Animated.timing(borderPulse, { toValue: 0, duration: 1000, useNativeDriver: true }),
        ])
      );
      loop.start();
      return () => loop.stop();
    } else {
      borderPulse.setValue(0);
    }
  }, [stage, borderPulse]);

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
          <Text className="text-[10px] font-semibold uppercase tracking-wider text-purple-500">
            Queued
          </Text>
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
            <Text className="text-[10px] font-semibold uppercase tracking-wider text-blue-500">
              Running
            </Text>
          </View>
          <Text className="text-sm font-medium text-typography-700">
            {formatElapsed(elapsed)}
          </Text>
        </HStack>
      );
    }
    return null;
  };

  return (
    <View style={{ marginBottom: 8 }}>
      <View
        className="overflow-hidden rounded-xl"
        style={{ borderWidth: 2, borderColor: restingBorder, backgroundColor: tint }}
      >
        {stage !== "complete" && (
          <Animated.View
            pointerEvents="none"
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              borderWidth: 1.5,
              borderColor,
              borderRadius: 12,
              opacity: borderPulse.interpolate({ inputRange: [0, 1], outputRange: [0.45, 1] }),
            }}
          />
        )}
        {/* Use plain View (not HStack) — gluestack HStack carries `p-0` in its
            base styles which, combined with tailwind's `important: 'html'`,
            beats any inline `padding*` we set here. View has no such reset. */}
        <View
          style={{
            width: "100%",
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            paddingLeft: 15,
            paddingRight: 15,
            paddingTop: 9,
            paddingBottom: 9,
            columnGap: 16,
          }}
        >
          {/* Left */}
          <VStack className="min-w-0 flex-1">
            <HStack className="items-center gap-2">
              <Text className="text-base font-medium text-typography-900" numberOfLines={1}>
                {item.model_name}
              </Text>
              <Text className="text-[11px] text-typography-300">{timeAgo}</Text>
            </HStack>
            <HStack className="mt-0.5 items-center gap-2">
              <Text className="text-xs text-typography-500" numberOfLines={1}>
                {item.provider_name}
              </Text>
              {/* Cloud / Local badge */}
              <View
                className={`rounded-md px-1.5 py-0.5 ${item.is_cloud ? "bg-cyan-500/10" : "bg-orange-500/10"}`}
              >
                <Text className={`text-[10px] font-semibold uppercase tracking-wider ${item.is_cloud ? "text-cyan-600 dark:text-cyan-300" : "text-orange-600 dark:text-orange-300"}`}>
                  {item.is_cloud ? "Cloud" : "Local"}
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
                  <View className={`rounded-md px-1.5 py-0.5 ${isCold ? "bg-sky-500/15" : "bg-orange-500/15"}`}>
                    <Text className={`text-[10px] font-semibold uppercase tracking-wider ${isCold ? "text-sky-600 dark:text-sky-300" : "text-orange-600 dark:text-orange-300"}`}>
                      {isCold ? "Cold" : "Hot"}
                    </Text>
                  </View>
                )}
                <Text className="text-base font-semibold text-typography-900">
                  {totalTimeLabel()}
                </Text>
              </HStack>
            )}
            {stage === "complete" && item.queue_seconds != null && item.duration != null && (
              <Text className="text-[11px] text-typography-500">
                queue {item.queue_seconds.toFixed(2)}s · exec {item.duration.toFixed(2)}s
              </Text>
            )}
          </VStack>
        </View>
      </View>
    </View>
  );
});

/* ── helper: merge WS live items with paginated items ── */

function mergeWithLive(
  liveRequests: RequestItem[],
  pageItems: PaginatedRequestItem[],
  perPage: number
): PaginatedRequestItem[] {
  // Convert each WS RequestItem into the paginated row shape. The
  // websocket payload is always at least as fresh as the paginated
  // fetch (it pushes on every state transition), so when a request
  // appears in both, the live copy must win — otherwise rows get
  // stuck on whatever state they were in when pageData was fetched.
  const toPaginated = (r: RequestItem): PaginatedRequestItem => ({
    request_id: r.request_id,
    model_name: r.model_name,
    provider_name: r.provider_name,
    // infer is_cloud from provider name (fallback when paginated
    // endpoint hasn't returned yet — pageData carries the real flag).
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
  });

  const liveById = new Map<string, PaginatedRequestItem>();
  for (const r of liveRequests) {
    liveById.set(r.request_id, toPaginated(r));
  }

  // Walk pageItems in order; replace each row with its live counterpart
  // if one exists, then append any live rows we haven't surfaced yet.
  const merged: PaginatedRequestItem[] = [];
  const seen = new Set<string>();
  for (const p of pageItems) {
    const overlay = liveById.get(p.request_id);
    if (overlay) {
      // Preserve the paginated `is_cloud` flag (the WS payload has to
      // infer it from the provider name); take everything else from
      // the live row so state transitions render immediately.
      merged.push({ ...overlay, is_cloud: p.is_cloud ?? overlay.is_cloud });
    } else {
      merged.push(p);
    }
    seen.add(p.request_id);
  }
  for (const [id, r] of liveById) {
    if (!seen.has(id)) merged.push(r);
  }

  return merged
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

const PER_PAGE = 5;

type PaginatedRequestListProps = {
  liveRequests: RequestItem[];
  apiKey: string | null;
  nowMs: number;
};

export default function PaginatedRequestList({
  liveRequests,
  apiKey,
  nowMs: _nowMs,
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

  // Single shared ticker for all card "time-ago" / "elapsed" labels. Cards
  // used to each spawn their own setInterval, which on a 7-card page meant
  // 7 timers + 7 component re-renders every second. Hoisting it here cuts
  // that to one timer + one parent render. The cadence is 1s while any
  // card is live and 10s when the whole list is complete.
  const hasLive = useMemo(
    () => displayItems.some((it) => deriveStage(it) !== "complete"),
    [displayItems]
  );
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const interval = hasLive ? 1000 : 10_000;
    const id = setInterval(() => setNow(Date.now()), interval);
    return () => clearInterval(id);
  }, [hasLive]);

  const totalPages = pageData?.total_pages ?? 1;

  return (
    <VStack className="w-full">
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
        <RequestRowSkeleton />
      ) : displayItems.length === 0 ? (
        <View className="items-center py-8">
          <Text className="text-sm text-typography-500">No requests yet.</Text>
        </View>
      ) : (
        <View className="w-full">
          {displayItems.map((req) => (
            <PaginatedRequestCard key={req.request_id} item={req} now={now} />
          ))}
        </View>
      )}

      {/* Pagination controls — compact footer band */}
      {totalPages > 1 && (
        <HStack
          className="items-center justify-between border-t border-outline-200"
          style={{ marginTop: 8, paddingTop: 8, paddingBottom: 4 }}
        >
          <Button
            size="xs"
            variant="link"
            isDisabled={page <= 1 || loading}
            onPress={() => load(page - 1)}
            className="px-1"
          >
            <ButtonText className="text-typography-500" style={{ fontSize: 12 }}>
              ← Prev
            </ButtonText>
          </Button>

          <HStack className="items-center" style={{ columnGap: 8 }}>
            <Text className="text-typography-500" style={{ fontSize: 12 }}>
              Page {page} of {totalPages}
            </Text>
            {loading && <ActivityIndicator size="small" color="#006DFF" />}
          </HStack>

          <Button
            size="xs"
            variant="link"
            isDisabled={page >= totalPages || loading}
            onPress={() => load(page + 1)}
            className="px-1"
          >
            <ButtonText className="text-typography-500" style={{ fontSize: 12 }}>
              Next →
            </ButtonText>
          </Button>
        </HStack>
      )}
    </VStack>
  );
}
