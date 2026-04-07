import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  View,
  Animated,
  Easing,
  LayoutAnimation,
  Platform,
  UIManager,
} from "react-native";
import { Text } from "@/components/ui/text";
import { HStack } from "@/components/ui/hstack";
import { VStack } from "@/components/ui/vstack";
import { Button, ButtonText } from "@/components/ui/button";
import { ChevronDown, ChevronUp } from "lucide-react-native";

if (
  Platform.OS === "android" &&
  UIManager.setLayoutAnimationEnabledExperimental
) {
  UIManager.setLayoutAnimationEnabledExperimental(true);
}

export type RequestStage = "queued" | "executing" | "complete";

export interface RequestItem {
  request_id: string;
  model_name: string;
  provider_name: string;
  status: string; // 'success', 'error', 'timeout', 'pending'
  timestamp: string | null;
  duration: number | null; // seconds (exec only)
  cold_start: boolean | null;
  enqueue_ts: string | null;
  scheduled_ts: string | null;
  request_complete_ts: string | null;
  queue_seconds: number | null;
  total_seconds: number | null; // enqueue to complete
  initial_priority: string | null;
  priority_when_scheduled: string | null;
  queue_depth_at_enqueue: number | null;
  error_message: string | null;
}

interface RequestStackProps {
  requests: RequestItem[];
}

function deriveStage(item: RequestItem): RequestStage {
  if (item.request_complete_ts) return "complete";
  if (item.scheduled_ts) return "executing";
  return "queued";
}

/** Border color based on stage + result status */
function getBorderColor(stage: RequestStage, status: string): string {
  if (stage === "queued") return "#8B5CF6"; // violet
  if (stage === "executing") return "#3B82F6"; // blue
  // complete
  switch (status.toLowerCase()) {
    case "success":
      return "#10B981"; // green
    case "error":
      return "#EF4444"; // red
    case "timeout":
      return "#F59E0B"; // amber
    default:
      return "#64748B"; // slate
  }
}

function withAlpha(hex: string, alphaHex: string): string {
  return `${hex}${alphaHex}`;
}

const STAGE_CONFIG: Record<
  RequestStage,
  { badgeLabel: string; badgeBg: string; badgeText: string }
> = {
  queued: {
    badgeLabel: "QUEUED",
    badgeBg: "bg-purple-500/10",
    badgeText: "text-purple-500",
  },
  executing: {
    badgeLabel: "RUNNING",
    badgeBg: "bg-blue-500/10",
    badgeText: "text-blue-500",
  },
  complete: {
    badgeLabel: "",
    badgeBg: "",
    badgeText: "",
  },
};

function formatTimeAgo(ts: string | null, nowMs: number): string {
  if (!ts) return "";
  const diffS = Math.max(0, (nowMs - new Date(ts).getTime()) / 1000);
  if (diffS < 60) return `${Math.round(diffS)}s ago`;
  const diffM = diffS / 60;
  if (diffM < 60) return `${Math.round(diffM)}m ago`;
  const diffH = diffM / 60;
  if (diffH < 24) return `${Math.round(diffH)}h ago`;
  const diffD = diffH / 24;
  if (diffD < 30) return `${Math.round(diffD)}d ago`;
  const diffMo = diffD / 30;
  return `${Math.round(diffMo)}mo ago`;
}

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}m ${s}s`;
}

function formatPriorityLabel(value: string): string {
  return value
    .toLowerCase()
    .replace(
      /(^|[\s-])([a-z])/g,
      (match, sep, letter) => `${sep}${letter.toUpperCase()}`
    );
}

export default function RequestStack({ requests }: RequestStackProps) {
  const [expanded, setExpanded] = useState(false);
  const [renderRequests, setRenderRequests] = useState<RequestItem[]>([]);
  const [exitingIds, setExitingIds] = useState<string[]>([]);
  const prevIdsRef = useRef<Set<string>>(new Set());
  const visibleIdsRef = useRef<Set<string>>(new Set());

  const newIds = useMemo(() => {
    const incoming = new Set(requests.map((r) => r.request_id));
    const prev = prevIdsRef.current;
    const fresh = new Set<string>();
    incoming.forEach((id) => {
      if (!prev.has(id)) fresh.add(id);
    });
    prevIdsRef.current = incoming;
    return fresh;
  }, [requests]);

  const visibleCount = expanded ? 10 : 5;
  const visibleRequests = useMemo(
    () => requests.slice(0, visibleCount),
    [requests, visibleCount]
  );
  const visibleIds = useMemo(
    () => new Set(visibleRequests.map((r) => r.request_id)),
    [visibleRequests]
  );
  const hasMore = requests.length > 5;

  useEffect(() => {
    visibleIdsRef.current = visibleIds;
  }, [visibleIds]);

  useEffect(() => {
    setRenderRequests((current) => {
      const nextIds = new Set(visibleRequests.map((r) => r.request_id));
      const exitingItems = current.filter((r) => !nextIds.has(r.request_id));
      setExitingIds((prev) => {
        const stillExiting = prev.filter((id) => !nextIds.has(id));
        const nextExiting = exitingItems.map((r) => r.request_id);
        return Array.from(new Set([...stillExiting, ...nextExiting]));
      });
      return [...visibleRequests, ...exitingItems];
    });
  }, [visibleRequests]);

  if (!requests.length) {
    return null;
  }

  return (
    <VStack space="xs" className="w-full">
      <VStack className="my-2.5 py-4">
        <Text className="mb-1 text-lg font-bold text-typography-900">
          Recent Requests
        </Text>
        <View className="w-full">
          {renderRequests.map((req) => (
            <AnimatedRequestCard
              key={req.request_id}
              item={req}
              isNew={newIds.has(req.request_id)}
              isExiting={exitingIds.includes(req.request_id)}
              isVisible={visibleIds.has(req.request_id)}
              onExitComplete={(id) => {
                if (visibleIdsRef.current.has(id)) return;
                LayoutAnimation.configureNext(
                  LayoutAnimation.Presets.easeInEaseOut
                );
                setExitingIds((prev) => prev.filter((entry) => entry !== id));
                setRenderRequests((prev) =>
                  prev.filter((entry) => entry.request_id !== id)
                );
              }}
            />
          ))}
        </View>

        {hasMore && (
          <Button
            variant="link"
            size="sm"
            onPress={() => {
              LayoutAnimation.configureNext(
                LayoutAnimation.Presets.easeInEaseOut
              );
              setExpanded(!expanded);
            }}
            className="mt-1 self-center"
          >
            <HStack space="xs" className="items-center">
              <ButtonText className="text-typography-500">
                {expanded ? "Show Less" : "Show More"}
              </ButtonText>
              {expanded ? (
                <ChevronUp size={16} color="#64748B" />
              ) : (
                <ChevronDown size={16} color="#64748B" />
              )}
            </HStack>
          </Button>
        )}
      </VStack>
    </VStack>
  );
}

function AnimatedRequestCard({
  item,
  isNew,
  isExiting,
  isVisible,
  onExitComplete,
}: {
  item: RequestItem;
  isNew: boolean;
  isExiting: boolean;
  isVisible: boolean;
  onExitComplete: (id: string) => void;
}) {
  const fadeAnim = useRef(new Animated.Value(isNew ? 0 : 1)).current;
  const slideAnim = useRef(new Animated.Value(isNew ? -8 : 0)).current;
  const scaleAnim = useRef(new Animated.Value(isNew ? 0.98 : 1)).current;

  useEffect(() => {
    if (isNew) {
      Animated.parallel([
        Animated.timing(fadeAnim, {
          toValue: 1,
          duration: 420,
          easing: Easing.out(Easing.cubic),
          useNativeDriver: true,
        }),
        Animated.timing(slideAnim, {
          toValue: 0,
          duration: 420,
          easing: Easing.out(Easing.cubic),
          useNativeDriver: true,
        }),
        Animated.timing(scaleAnim, {
          toValue: 1,
          duration: 420,
          easing: Easing.out(Easing.cubic),
          useNativeDriver: true,
        }),
      ]).start();
    }
  }, []);

  useEffect(() => {
    if (!isExiting && isVisible) {
      Animated.parallel([
        Animated.timing(fadeAnim, {
          toValue: 1,
          duration: 320,
          easing: Easing.out(Easing.cubic),
          useNativeDriver: true,
        }),
        Animated.timing(slideAnim, {
          toValue: 0,
          duration: 320,
          easing: Easing.out(Easing.cubic),
          useNativeDriver: true,
        }),
        Animated.timing(scaleAnim, {
          toValue: 1,
          duration: 320,
          easing: Easing.out(Easing.cubic),
          useNativeDriver: true,
        }),
      ]).start();
    }
  }, [isExiting, isVisible]);

  useEffect(() => {
    if (isExiting) {
      Animated.parallel([
        Animated.timing(fadeAnim, {
          toValue: 0,
          duration: 260,
          easing: Easing.in(Easing.cubic),
          useNativeDriver: true,
        }),
        Animated.timing(slideAnim, {
          toValue: 8,
          duration: 260,
          easing: Easing.in(Easing.cubic),
          useNativeDriver: true,
        }),
        Animated.timing(scaleAnim, {
          toValue: 0.98,
          duration: 260,
          easing: Easing.in(Easing.cubic),
          useNativeDriver: true,
        }),
      ]).start(({ finished }) => {
        if (finished) onExitComplete(item.request_id);
      });
    }
  }, [isExiting, item.request_id, onExitComplete]);

  return (
    <Animated.View
      style={{
        opacity: fadeAnim,
        transform: [{ translateY: slideAnim }, { scale: scaleAnim }],
      }}
    >
      <RequestCard item={item} />
    </Animated.View>
  );
}

function RequestCard({ item }: { item: RequestItem }) {
  const stage = deriveStage(item);
  const stageConfig = STAGE_CONFIG[stage];
  const borderColor = getBorderColor(stage, item.status);
  const borderTint = withAlpha(borderColor, "0D");

  // Subtle pulse overlay for in-flight stages
  const borderPulse = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (stage !== "complete") {
      const loop = Animated.loop(
        Animated.sequence([
          Animated.timing(borderPulse, {
            toValue: 1,
            duration: 1100,
            useNativeDriver: true,
          }),
          Animated.timing(borderPulse, {
            toValue: 0,
            duration: 1100,
            useNativeDriver: true,
          }),
        ])
      );
      loop.start();
      return () => loop.stop();
    } else {
      borderPulse.setValue(0);
    }
  }, [stage]);

  // Live timer
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const interval = stage === "complete" ? 10000 : 1000;
    const id = setInterval(() => setNow(Date.now()), interval);
    return () => clearInterval(id);
  }, [stage]);

  const isCloud =
    item.provider_name?.toLowerCase().includes("openai") ||
    item.provider_name?.toLowerCase().includes("azure") ||
    item.provider_name?.toLowerCase().includes("cloud");

  const isCold = item.cold_start === true;
  const isLocal = !isCloud;
  const timeAgo = formatTimeAgo(item.enqueue_ts || item.timestamp, now);

  const totalTimeLabel = (): string => {
    if (stage === "complete" && item.total_seconds != null) {
      return `${item.total_seconds.toFixed(2)}s`;
    }
    if (item.enqueue_ts) {
      return formatElapsed((now - new Date(item.enqueue_ts).getTime()) / 1000);
    }
    return "...";
  };

  const renderRightSide = () => {
    if (stage === "queued") {
      return (
        <VStack className="shrink-0 items-end">
          <View
            className={`rounded-md px-2 py-0.5 ${stageConfig.badgeBg} transition-colors duration-300`}
          >
            <Text
              className={`text-sm font-semibold ${stageConfig.badgeText} transition-colors duration-300`}
            >
              {stageConfig.badgeLabel}
            </Text>
          </View>
          <HStack space="sm">
            {item.initial_priority && (
              <Text className="text-sm text-typography-400">
                {formatPriorityLabel(item.initial_priority)} priority
              </Text>
            )}
            {item.queue_depth_at_enqueue != null &&
              item.queue_depth_at_enqueue > 0 && (
                <Text className="text-sm text-typography-400">
                  | Queued at #{item.queue_depth_at_enqueue}
                </Text>
              )}
          </HStack>
        </VStack>
      );
    }

    if (stage === "executing") {
      const elapsed = item.scheduled_ts
        ? (now - new Date(item.scheduled_ts).getTime()) / 1000
        : 0;
      return (
        <VStack className="shrink-0 items-end">
          <HStack space="sm" className="items-center">
            <View
              className={`rounded-md px-2 py-0.5 ${stageConfig.badgeBg} transition-colors duration-300`}
            >
              <Text
                className={`text-sm font-semibold ${stageConfig.badgeText} transition-colors duration-300`}
              >
                {stageConfig.badgeLabel}
              </Text>
            </View>
            <Text className="text-base font-medium text-typography-700">
              {formatElapsed(elapsed)}
            </Text>
          </HStack>
          {item.queue_seconds != null && (
            <Text className="text-sm text-typography-400">
              Waited for {item.queue_seconds.toFixed(1)}s
            </Text>
          )}
        </VStack>
      );
    }

    // Complete stage
    return (
      <VStack className="shrink-0 items-end">
        <HStack space="sm" className="items-center">
          {isLocal && (
            <View
              className={`rounded-md px-2 py-0.5 transition-colors duration-300 ${
                isCold ? "bg-sky-600/15" : "bg-orange-600/15"
              }`}
            >
              <Text
                className={`text-xs font-semibold transition-colors duration-300 ${
                  isCold ? "text-sky-400" : "text-orange-400"
                }`}
              >
                {isCold ? "COLD" : "HOT"}
              </Text>
            </View>
          )}
          <Text className="text-lg font-semibold text-typography-900">
            {totalTimeLabel()}
          </Text>
        </HStack>
        <Text className="text-sm text-typography-400">
          {item.queue_seconds != null && item.duration != null
            ? `Queue time: ${item.queue_seconds.toFixed(1)}s | Execution time: ${item.duration.toFixed(1)}s`
            : timeAgo}
        </Text>
      </VStack>
    );
  };

  return (
    <View className="mb-1.5">
      <Animated.View
        className="relative transition-colors duration-500"
        style={{
          borderWidth: 2,
          borderColor,
          borderRadius: 10,
          backgroundColor: borderTint,
        }}
      >
        {stage !== "complete" && (
          <Animated.View
            pointerEvents="none"
            className="absolute inset-0 transition-colors duration-500"
            style={{
              borderWidth: 2,
              borderColor,
              borderRadius: 10,
              opacity: borderPulse.interpolate({
                inputRange: [0, 1],
                outputRange: [0.2, 0.6],
              }),
            }}
          />
        )}
        <HStack className="w-full items-center px-3 py-2.5" space="md">
          {/* Left: model + provider (consistent layout, no conditional badge here) */}
          <VStack className="min-w-0 flex-1">
            <HStack space="sm" className="items-center">
              <Text
                className="text-lg font-medium text-typography-900"
                numberOfLines={1}
              >
                {item.model_name}
              </Text>
              <Text className="text-sm text-typography-400">{timeAgo}</Text>
            </HStack>
            <Text
              className="text-base font-medium text-typography-400"
              numberOfLines={1}
            >
              {item.provider_name}
            </Text>
            {stage === "complete" &&
              item.status === "error" &&
              item.error_message && (
                <Text className="text-xs text-red-500" numberOfLines={1}>
                  {item.error_message.length > 50
                    ? item.error_message.slice(0, 50) + "..."
                    : item.error_message}
                </Text>
              )}
          </VStack>

          {/* Right: stage-specific info */}
          {renderRightSide()}
        </HStack>
      </Animated.View>
    </View>
  );
}
