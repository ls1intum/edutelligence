import React from "react";
import { Text } from "@/components/ui/text";

export type BudgetBucket = {
  seriesKey: string;
  bucketTs: number;
  costMicroCents: number;
};

type Props = {
  data: BudgetBucket[];
  title?: string;
  height?: number;
  xAxisFormat?: string;
  rangeStart?: number;
  rangeEnd?: number;
  barWidthMs?: number;
};

export default function BudgetHistoryChart(_props: Props) {
  return <Text>Charts not supported on native.</Text>;
}
