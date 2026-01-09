import React, { useEffect, useRef, useState } from "react";
import { View, Animated, LayoutAnimation, Platform, UIManager } from "react-native";
import { Text } from "@/components/ui/text";
import { HStack } from "@/components/ui/hstack";
import { VStack } from "@/components/ui/vstack";
import { Button, ButtonText } from "@/components/ui/button";
import { AlertTriangle, ChevronDown, ChevronUp } from "lucide-react-native";

if (
  Platform.OS === "android" &&
  UIManager.setLayoutAnimationEnabledExperimental
) {
  UIManager.setLayoutAnimationEnabledExperimental(true);
}

export interface RequestItem {
  request_id: string;
  model_name: string;
  provider_name: string;
  status: string; // 'success', 'error', 'timeout', etc.
  timestamp: string | null;
  duration: number | null; // seconds
  cold_start: boolean | null;
}

interface RequestStackProps {
  requests: RequestItem[];
  error?: string | null;
}

const STATUS_COLORS: Record<string, string> = {
  success: "#10B981", // emerald-500
  error: "#EF4444", // red-500
  timeout: "#F59E0B", // amber-500
  unknown: "#64748B", // slate-500
};

export default function RequestStack({ requests, error }: RequestStackProps) {

  const [expanded, setExpanded] = useState(false);

  if (error) {
    return (
      <View className="mb-4 w-full rounded-lg border border-red-500/20 bg-red-500/10 p-4">
         <HStack space="sm" className="items-center justify-center">
            <AlertTriangle size={16} className="text-red-500"/>
            <Text className="text-sm text-red-500">
               Failed to load latest requests: {error}
            </Text>
         </HStack>
      </View>
    );
  }

  if (!requests.length) {
    return null; // Or return a "No requests" placeholder?
  }

  // Toggle visibility logic
  // Show 5 by default, 10 if expanded
  const visibleCount = expanded ? 10 : 5;
  const visibleRequests = requests.slice(0, visibleCount);
  const hasMore = requests.length > 5;

  return (
    <VStack space="sm" className="w-full mb-4">
      <Text className="mb-2 text-lg font-bold text-typography-900">
        Recent Requests
      </Text>
      <View className="w-full space-y-6">
        {visibleRequests.map((req) => (
          <RequestCard 
            key={req.request_id} 
            item={req} 
          />
        ))}
      </View>
      
      {hasMore && (
        <Button
          variant="link"
          size="sm"
          onPress={() => {
            LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
            setExpanded(!expanded);
          }}
          className="self-center mt-2"
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
  );
}

function RequestCard({ item }: { item: RequestItem }) {
  const color =
    STATUS_COLORS[item.status.toLowerCase()] || STATUS_COLORS.unknown;
  
  const isCloud =
    item.provider_name?.toLowerCase().includes("openai") ||
    item.provider_name?.toLowerCase().includes("azure") ||
    item.provider_name?.toLowerCase().includes("cloud");

  const isCold = item.cold_start === true;
  // "HOT" logic: local (not cloud) and not cold.
  const isHot = !isCloud && !isCold;

  const timeLabel = item.timestamp
    ? new Date(item.timestamp).toLocaleTimeString([], {
        hour12: false,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "--:--:--";

  return (
    <View>
      <HStack
        className="w-full items-center justify-between rounded-lg border border-outline-200 bg-secondary-200 p-3"
        space="md"
      >
        {/* Left: Status Indicator & Model */}
        <HStack space="sm" className="items-center">
          <View
            style={{ backgroundColor: color }}
            className="h-2 w-2 rounded-full"
          />
          <VStack>
            <Text className="text-base font-medium text-typography-900">
              {item.model_name}
            </Text>
            <Text className="text-xs text-typography-500">
              {item.provider_name}
            </Text>
          </VStack>
        </HStack>

        <VStack className="items-end">
          <HStack space="sm" className="items-center">
            {isCold && (
              <View className="rounded px-1.5 py-0.5 border-blue-500/20 bg-blue-500/10">
                <Text
                  className="text-[10px] text-blue-500"
                >
                  COLD
                </Text>
              </View>
            )}
             {!isCold && !isCloud && (
              <View className="rounded px-1.5 py-0.5 border-red-500/20 bg-red-500/10">
                <Text
                  className="text-[10px] text-red-500"
                >
                  HOT
                </Text>
              </View>
            )}

            <Text className="text-xs font-medium text-typography-700">
              {item.duration ? `${item.duration.toFixed(2)}s` : "..."}
            </Text>
          </HStack>
          <Text className="text-xs text-typography-400">{timeLabel}</Text>
        </VStack>
      </HStack>
    </View>
  );
}
