import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Animated, Easing, PanResponder, View } from "react-native";
import { LineChart } from "react-native-gifted-charts";

import { Button, ButtonIcon } from "@/components/ui/button";
import { CheckIcon } from "@/components/ui/icon";
import EmptyState from "@/components/statistics/empty-state";
import type { SelectionState } from "@/components/statistics/types";

type InteractiveZoomableChartProps = {
  width: number;
  totalLineData: any[];
  cloudLineData: any[];
  localLineData: any[];
  onZoom: (range: { start: Date; end: Date }) => void;
  colors: { total: string; cloud: string; local: string };
};

export default function InteractiveZoomableChart({
  width,
  totalLineData,
  cloudLineData,
  localLineData,
  onZoom,
  colors,
}: InteractiveZoomableChartProps) {
  const [selection, setSelection] = useState<SelectionState | null>(null);
  const selectionRef = useRef<SelectionState | null>(null);
  const containerRef = useRef<View | null>(null);
  const confirmAnim = useRef(new Animated.Value(0)).current;

  // Chart layout constants - must match LineChart props
  // Note: LineChart adds yAxisLabelWidth ON TOP of the width prop, so we subtract it
  const yAxisLabelWidth = 35; // Space for y-axis labels on the left
  const initialSpacing = 0; // No extra spacing at the start
  const endSpacing = 0; // Keep at 0 - adjustToWidth doesn't work well with endSpacing
  const rightPadding = 16; // Visual padding so the line doesn't feel cut off at the right edge
  const chartLeftOffset = yAxisLabelWidth + initialSpacing; // Where the data area starts in container
  const chartWidth = Math.max(width - yAxisLabelWidth - rightPadding, 0); // Width passed to LineChart
  const dataAreaWidth = chartWidth - initialSpacing - endSpacing; // Actual plottable data area (= chartWidth)

  const MIN_SELECTION_PX = 14; // allow small selections, but avoid accidental taps
  const EDGE_SNAP_PX = 16; // snap to the right-most data when dragging near the chart edge
  const chartHeight = 250; // Match LineChart height

  // Clamp selection X to container bounds during dragging (allows overflow past data area)
  const clampSelectionXDragging = useCallback(
    (x: number) => Math.max(0, Math.min(width, x)),
    [width]
  );

  // Clamp selection X to the actual data area (used on release for final position)
  const clampSelectionXFinal = useCallback(
    (x: number) => Math.max(chartLeftOffset, Math.min(chartLeftOffset + dataAreaWidth, x)),
    [chartLeftOffset, dataAreaWidth]
  );

  // Helper: Map x in container-space to timestamp (accounts for y-axis offset)
  const getTimestampFromX = useCallback(
    (x: number) => {
      if (!totalLineData.length) return 0;
      const firstTs = totalLineData[0].timestamp;
      const lastTs = totalLineData[totalLineData.length - 1].timestamp;
      const duration = lastTs - firstTs;
      if (dataAreaWidth <= 0 || duration <= 0) return lastTs;
      // Convert container X to data-area-relative X
      const dataX = Math.max(0, Math.min(x - chartLeftOffset, dataAreaWidth));
      const pct = dataX / dataAreaWidth;
      return firstTs + pct * duration;
    },
    [totalLineData, dataAreaWidth, chartLeftOffset]
  );

  const confirmSelection = useCallback(() => {
    if (!selection || !selection.confirmable) return;
    const startX = Math.min(selection.start, selection.end);
    const endX = Math.max(selection.start, selection.end);
    const startTs = getTimestampFromX(startX);
    const endTs = getTimestampFromX(endX);

    setSelection(null);
    selectionRef.current = null;
    onZoom({ start: new Date(startTs), end: new Date(endTs) });
  }, [selection, getTimestampFromX, onZoom]);

  useEffect(() => {
    if (selection?.confirmable) {
      confirmAnim.setValue(0);
      Animated.timing(confirmAnim, {
        toValue: 1,
        duration: 100,
        easing: Easing.out(Easing.quad),
        useNativeDriver: true,
      }).start();
    } else {
      confirmAnim.setValue(0);
    }
  }, [selection?.confirmable, confirmAnim]);

  const panResponder = useMemo(
    () =>
      PanResponder.create({
        // Capture horizontal drags (differentiate from vertical scroll)
        onMoveShouldSetPanResponderCapture: (_, gestureState) => {
          return (
            Math.abs(gestureState.dx) > 5 &&
            Math.abs(gestureState.dy) < Math.abs(gestureState.dx)
          );
        },

        onPanResponderGrant: (_evt, gestureState) => {
          // Measure relative to page to be robust against child targets (web issue)
          containerRef.current?.measure((_x, _y, _w, _h, pageX, _pageY) => {
            const localStart = clampSelectionXDragging(gestureState.x0 - pageX);
            const newSel: SelectionState = {
              start: localStart,
              end: localStart,
              active: true,
              pageX,
              confirmable: false,
            };
            selectionRef.current = newSel;
            setSelection({ ...newSel });
          });
        },

        onPanResponderMove: (_evt, gestureState) => {
          const sel = selectionRef.current;
          if (!sel) return;

          // Calculate new end based on moveX and captured pageX (allow dragging beyond data area)
          let localEnd = clampSelectionXDragging(gestureState.moveX - (sel.pageX || 0));

          // update ref
          sel.end = localEnd;
          sel.confirmable = false;
          // update state for render
          setSelection({ start: sel.start, end: localEnd, active: true });
        },

        onPanResponderRelease: () => {
          const sel = selectionRef.current;
          if (!sel) {
            setSelection(null);
            selectionRef.current = null;
            return;
          }

          const rawStart = Math.min(sel.start, sel.end);
          const rawEnd = Math.max(sel.start, sel.end);
          const dataAreaRight = chartLeftOffset + dataAreaWidth;
          // Snap to edges if dragged beyond or near the data area bounds
          const hitRightEdge = rawEnd >= dataAreaRight - EDGE_SNAP_PX;
          const hitLeftEdge = rawStart <= chartLeftOffset + EDGE_SNAP_PX;

          // Clamp to data area bounds on release (snaps overflow to min/max)
          const startX = hitLeftEdge ? chartLeftOffset : clampSelectionXFinal(rawStart);
          const endX = hitRightEdge ? dataAreaRight : clampSelectionXFinal(rawEnd);
          const finalStart = Math.min(startX, endX);
          const finalEnd = Math.max(startX, endX);
          const span = finalEnd - finalStart;

          if (span > MIN_SELECTION_PX || hitRightEdge) {
            const finalized: SelectionState = {
              start: finalStart,
              end: finalEnd,
              active: false,
              confirmable: true,
            };
            selectionRef.current = finalized;
            setSelection(finalized);
          } else {
            setSelection(null);
            selectionRef.current = null;
          }
        },
        onPanResponderTerminate: () => {
          setSelection(null);
          selectionRef.current = null;
        },
      }),
    [clampSelectionXDragging, clampSelectionXFinal, chartLeftOffset, dataAreaWidth]
  );

  return totalLineData.length ? (
    <View
      ref={containerRef}
      {...panResponder.panHandlers}
      className="web:select-none"
      style={{
        position: "relative",
        width: width,
        height: 340,
        justifyContent: "center",
        backgroundColor: "transparent",
        userSelect: "none" as any,
      }}
    >
      {selection ? (
        <View
          pointerEvents="box-none"
          style={{
            position: "absolute",
            left: Math.min(selection.start, selection.end),
            width: Math.abs(selection.end - selection.start),
            top: 0,
            bottom: 20,
            zIndex: 999,
          }}
        >
          <View
            pointerEvents="none"
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              top: 0,
              bottom: 0,
              backgroundColor: "rgba(59, 233, 222, 0.3)",
              borderWidth: 1,
              borderColor: "#3BE9DE",
            }}
          />
          {selection.confirmable && (
            <Animated.View
              style={{
                alignItems: "center",
                paddingTop: 8,
                opacity: confirmAnim,
                transform: [
                  {
                    scale: confirmAnim.interpolate({
                      inputRange: [0, 1],
                      outputRange: [0.95, 1],
                    }),
                  },
                ],
              }}
            >
              <Button
                size="sm"
                action="positive"
                onPress={confirmSelection}
                className="h-12 w-12 rounded-full shadow-hard-1"
                accessibilityLabel="Apply zoom"
              >
                <ButtonIcon as={CheckIcon} className="h-6 w-6 text-white" />
              </Button>
            </Animated.View>
          )}
        </View>
      ) : null}
      <View pointerEvents={selection?.active ? "none" : "auto"}>
        <LineChart
          isAnimated={true}
          key={
            totalLineData.length
              ? `${totalLineData[0].timestamp}-${
                  totalLineData[totalLineData.length - 1].timestamp
                }`
              : "chart"
          }
          height={chartHeight}
          data={totalLineData}
          data2={cloudLineData}
          data3={localLineData}
          disableScroll
          adjustToWidth
          hideDataPoints
          width={chartWidth}
          yAxisLabelWidth={yAxisLabelWidth}
          initialSpacing={initialSpacing}
          endSpacing={endSpacing}
          thickness={4}
          color1={colors.total}
          color2={colors.cloud}
          thickness2={3}
          color3={colors.local}
          thickness3={3}
          rulesType="dashed"
          rulesColor="#525252"
          yAxisThickness={0}
          xAxisType="dashed"
          xAxisColor="#525252"
          yAxisTextStyle={{ color: "#64748B", top: 4 }} // Slate-500
          xAxisLabelTextStyle={{
            color: "#64748B",
            textAlign: "center",
            lineHeight: 14,
            fontSize: 11,
          }} // Slate-500
          xAxisTextNumberOfLines={1}
          labelsExtraHeight={20}
          noOfSections={5}
          curved
          areaChart
          startFillColor1={colors.total}
          endFillColor1={colors.total}
          startOpacity1={0.3}
          endOpacity1={0.1}
          startFillColor2={colors.cloud}
          endFillColor2={colors.cloud}
          startOpacity2={0.3}
          endOpacity2={0.1}
          startFillColor3={colors.local}
          endFillColor3={colors.local}
          startOpacity3={0.3}
          endOpacity3={0.1}
        />
      </View>
    </View>
  ) : (
    <EmptyState message="No timeline data available." />
  );
}
