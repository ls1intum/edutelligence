import React from "react";
import { ActivityIndicator, ScrollView, View } from "react-native";
import { LineChart } from "react-native-gifted-charts";
import { RotateCw } from "lucide-react-native";

import { Button, ButtonIcon } from "@/components/ui/button";
import { Text } from "@/components/ui/text";
import EmptyState from "@/components/statistics/empty-state";
import { CHART_PALETTE } from "@/components/statistics/constants";

type VramChartProps = {
  width: number;
  vramDayOffset: number;
  setVramDayOffset: (offset: number) => void;
  fetchVramStats: (options?: { silent?: boolean }) => void;
  isVramLoading: boolean;
  vramError: string | null;
  vramDataByProvider: { [url: string]: Array<any> };
  vramBaseline: any[];
  vramBucketSizeSec: number;
  vramTotalBuckets: number;
  getProviderColor: (index: number) => string;
  nowRef: number;
};

export default function VramChart({
  width,
  vramDayOffset,
  setVramDayOffset,
  fetchVramStats,
  isVramLoading,
  vramError,
  vramDataByProvider,
  vramBaseline,
  vramBucketSizeSec,
  vramTotalBuckets,
  getProviderColor,
  nowRef,
}: VramChartProps) {
  const dayButtons = Array.from({ length: 7 }).map((_, idx) => {
    const label =
      idx === 0 ? "Today" : idx === 1 ? "Yesterday" : `${idx} days ago`;
    const isActive = vramDayOffset === idx;
    return (
      <Button
        key={idx}
        size="sm"
        variant={isActive ? "solid" : "outline"}
        className="mb-2 mr-2"
        onPress={() => setVramDayOffset(idx)}
        accessibilityLabel={`Load VRAM for ${label}`}
      >
        <Text
          className={
            isActive ? "text-typography-200" : "text-typography-900"
          }
        >
          {label}
        </Text>
      </Button>
    );
  });

  const controls = (
    <View
      style={{
        flexDirection: "row",
        flexWrap: "wrap",
        marginBottom: 12,
      }}
    >
      {dayButtons}
      <Button
        size="sm"
        variant="solid"
        action="primary"
        className="mb-2 mr-2 h-9 w-9 items-center justify-center rounded-full p-0 text-typography-200"
        onPress={() => fetchVramStats()}
        accessibilityLabel="Refresh VRAM Stats"
      >
        <ButtonIcon as={RotateCw} />
      </Button>
    </View>
  );

  if (isVramLoading) {
    return (
      <View>
        {controls}
        <View
          style={{
            height: 220,
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <ActivityIndicator size="large" color="#006DFF" />
        </View>
      </View>
    );
  }

  if (vramError) {
    return (
      <View>
        {controls}
        <EmptyState message={vramError} />
      </View>
    );
  }

  const providers = Object.keys(vramDataByProvider);
  const displayData = vramDataByProvider;
  if (providers.length === 0) {
    return (
      <View>
        {controls}
        <EmptyState message="No VRAM data available for the selected day." />
      </View>
    );
  }

  return (
    <View>
      {controls}
      {/* Legend */}
      <View
        style={{
          flexDirection: "row",
          flexWrap: "wrap",
          marginBottom: 16,
          paddingHorizontal: 8,
        }}
      >
        {providers.map((url, index) => {
          if (url === "No Data") return null;
          const color = getProviderColor(index);
          const shortUrl = url.replace("http://", "").split(":")[0];

          return (
            <View
              key={url}
              style={{
                flexDirection: "row",
                alignItems: "center",
                marginRight: 16,
                marginBottom: 8,
              }}
            >
              <View
                style={{
                  width: 12,
                  height: 12,
                  backgroundColor: color,
                  borderRadius: 2,
                  marginRight: 6,
                }}
              />
              <Text
                style={{
                  fontSize: 12,
                  color: CHART_PALETTE.textLight,
                }}
              >
                {shortUrl}
              </Text>
            </View>
          );
        })}
      </View>

      {/* Multi-line Chart */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={true}
        style={{ maxWidth: width - 32 }}
        contentContainerStyle={{
          paddingRight: 70,
          paddingLeft: 0,
        }}
      >
        {(() => {
          const VRAM_SPACING = 1; // pixels per bucket
          const bucketsPerHour = 3600 / vramBucketSizeSec;
          const PIXELS_PER_HOUR = VRAM_SPACING * bucketsPerHour;

          const yAxisLabelWidth = 38;
          const initialSpacing = 0;
          const endSpacing = 50;

          const totalBuckets = vramTotalBuckets || 8640;
          const chartWidth =
            totalBuckets * VRAM_SPACING + initialSpacing + endSpacing;

          const dataSet: any[] = [];
          if (vramBaseline.length) {
            dataSet.push({
              data: vramBaseline,
              color: "transparent",
              thickness: 0.0001,
              hideDataPoints: true,
              hidePointers: true,
            });
          }
          providers.forEach((url, idx) => {
            dataSet.push({
              data: displayData[url] || [],
              color: getProviderColor(idx),
              thickness: 1.5,
              hideDataPoints: true,
              dataPointsRadius: 2,
              dataPointsColor: getProviderColor(idx),
              areaChart: true,
              startFillColor: getProviderColor(idx),
              endFillColor: getProviderColor(idx),
              startOpacity: 0.3,
              endOpacity: 0.1,
            });
          });

          // Manual Hour Labels
          const hourLabels = [];
          for (let h = 0; h <= 24; h++) {
            hourLabels.push({
              time: `${h}:00`,
              x: initialSpacing + h * PIXELS_PER_HOUR,
            });
          }

          // Calculate "now" position if viewing today (in UTC)
          const now = new Date(nowRef);
          const isToday = vramDayOffset === 0;
          let nowXPosition: number | null = null;

          if (isToday) {
            const nowMs = now.getTime();
            const todayUtc = new Date(
              Date.UTC(
                now.getUTCFullYear(),
                now.getUTCMonth(),
                now.getUTCDate()
              )
            );
            const todayStartMs = todayUtc.getTime();

            const diffSec = (nowMs - todayStartMs) / 1000;
            if (diffSec >= 0 && diffSec <= 86400) {
              const bucketsFromStart = diffSec / vramBucketSizeSec;
              nowXPosition =
                initialSpacing + bucketsFromStart * VRAM_SPACING;
            }
          }

          return (
            <View style={{ position: "relative", paddingBottom: 40 }}>
              <LineChart
                key={`vram-${vramDayOffset}-${Object.keys(displayData).length}-${Object.values(displayData)
                  .map((d) => d.length)
                  .reduce((a, b) => a + b, 0)}`}
                isAnimated={true}
                dataSet={dataSet}
                height={220}
                adjustToWidth={false}
                width={chartWidth}
                initialSpacing={initialSpacing}
                endSpacing={endSpacing}
                spacing={VRAM_SPACING}
                yAxisThickness={0}
                yAxisLabelWidth={yAxisLabelWidth}
                xAxisThickness={1}
                xAxisColor="#334155"
                yAxisTextStyle={{
                  color: CHART_PALETTE.textLight,
                  fontSize: 10,
                  top: 4,
                }}
                hideAxesAndRules={false}
                rulesType="dashed"
                rulesColor="#334155"
                dashWidth={4}
                dashGap={4}
                noOfSections={5}
                yAxisLabelSuffix=" GB"
                xAxisLabelsHeight={0}
                pointerConfig={{
                  pointerStripHeight: 220,
                  pointerStripColor: CHART_PALETTE.textLight,
                  pointerStripWidth: 1,
                  pointerColor: CHART_PALETTE.provider1,
                  radius: 4,
                  pointerLabelWidth: 160,
                  pointerLabelHeight: 110,
                  activatePointersOnLongPress: false,
                  autoAdjustPointerLabelPosition: true,
                  pointerLabelComponent: (items: any) => {
                    const providerItems = (items || []).filter(
                      (item: any) =>
                        item && !item._empty && !item._isBaseline
                    );

                    const anyItem = (items || [])[0];
                    const ts = anyItem?.timestamp;
                    const labelText = ts
                      ? new Date(ts).toLocaleTimeString("en-GB", {
                          hour: "2-digit",
                          minute: "2-digit",
                          second: "2-digit",
                          timeZone: "UTC",
                        })
                      : anyItem?.label || "";

                    return (
                      <View
                        style={{
                          backgroundColor: "#1f2937",
                          padding: 8,
                          borderRadius: 8,
                          borderWidth: 1,
                          borderColor: "#374151",
                        }}
                      >
                        <Text
                          style={{
                            color: "#9ca3af",
                            fontSize: 10,
                            marginBottom: 4,
                          }}
                        >
                          {labelText}
                        </Text>
                        {providerItems.length === 0 ? (
                          <Text
                            style={{
                              color: "#ef4444",
                              fontSize: 10,
                              fontWeight: "600",
                            }}
                          >
                            No connection to the server
                          </Text>
                        ) : (
                          providerItems.map((item: any, index: number) => {
                            return (
                              <View key={index} style={{ marginTop: 6 }}>
                                <View
                                  style={{
                                    flexDirection: "row",
                                    alignItems: "center",
                                  }}
                                >
                                  <View
                                    style={{
                                      width: 8,
                                      height: 8,
                                      backgroundColor:
                                        item.dataPointsColor || "gray",
                                      borderRadius: 2,
                                      marginRight: 6,
                                    }}
                                  />
                                  <View>
                                    <Text
                                      style={{
                                        color: "white",
                                        fontSize: 10,
                                      }}
                                    >
                                      {item.remaining_vram_gb} GB free
                                    </Text>
                                    <Text
                                      style={{
                                        color: "#e2e8f0",
                                        fontSize: 10,
                                      }}
                                    >
                                      Used: {item.used_vram_gb} GB
                                    </Text>
                                  </View>
                                </View>
                                {/* Loaded Models */}
                                {item.loaded_model_names &&
                                  item.loaded_model_names.length > 0 && (
                                    <View
                                      style={{
                                        marginTop: 4,
                                        paddingLeft: 14,
                                      }}
                                    >
                                      {item.loaded_model_names.map(
                                        (name: string, mIdx: number) => (
                                          <Text
                                            key={mIdx}
                                            style={{
                                              color: "#F29C6E",
                                              fontSize: 9,
                                            }}
                                          >
                                            • {name}
                                          </Text>
                                        )
                                      )}
                                    </View>
                                  )}
                              </View>
                            );
                          })
                        )}
                      </View>
                    );
                  },
                }}
                interpolateMissingValues={false}
              />
              {/* "Now" indicator line */}
              {nowXPosition !== null && (
                <View
                  style={{
                    position: "absolute",
                    left: Math.max((nowXPosition ?? 0) - 1, 0),
                    top: 0,
                    bottom: 0,
                    width: 1,
                    borderStyle: "dashed",
                    borderWidth: 1,
                    borderColor: "#ef4444",
                    zIndex: 10,
                    pointerEvents: "none",
                  }}
                >
                  <View
                    style={{
                      position: "absolute",
                      top: -16,
                      left: -14,
                      backgroundColor: "#ef4444",
                      paddingHorizontal: 4,
                      borderRadius: 4,
                    }}
                  >
                    <Text
                      style={{
                        color: "white",
                        fontSize: 9,
                        fontWeight: "bold",
                      }}
                    >
                      NOW
                    </Text>
                  </View>
                </View>
              )}
              {/* Custom X Axis Labels */}
              <View
                style={{
                  position: "absolute",
                  bottom: 5,
                  left: 0,
                  right: 0,
                  height: 30,
                }}
              >
                {hourLabels.map((lbl, i) => (
                  <Text
                    key={i}
                    style={{
                      position: "absolute",
                      left: lbl.x - 10,
                      color: CHART_PALETTE.textLight,
                      fontSize: 10,
                    }}
                  >
                    {lbl.time}
                  </Text>
                ))}
              </View>
            </View>
          );
        })()}
      </ScrollView>
    </View>
  );
}
