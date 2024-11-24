"use client";

import * as React from "react";
import { Area, AreaChart, CartesianGrid, XAxis } from "recharts";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { generateColor } from "@/lib/utils";

interface EndpointActivityProps {
  title: string;
  description: string;
  chartData: ChartDataItemDAO[];
}

function generateChartConfig(chartData: ChartDataItemDAO[]): ChartConfig {
  const endpoints = Object.keys(chartData[0]).filter((key) => key !== "date");
  const chartConfig: ChartConfig = {};

  endpoints.forEach((endpoint, index) => {
    chartConfig[endpoint] = {
      label: endpoint,
      color: generateColor(index),
    };
  });

  return chartConfig;
}

export function EndpointActivity({ title, description, chartData }: EndpointActivityProps) {

  const endpoints = Object.keys(chartData[0]).filter((key) => key !== "date");

  return (
    <Card>
      <CardHeader className="flex items-center gap-2 space-y-0 py-5 sm:flex-row">
        <div className="grid flex-1 gap-1 text-center sm:text-left">
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="px-2 pt-4 sm:px-6 sm:pt-6">
        <ChartContainer
          config={generateChartConfig(chartData)}
          className="aspect-auto h-[250px] w-full">
          <AreaChart data={chartData}>
            <defs>
              {endpoints.map((endpoint, index) => {
                const color = generateColor(index);
                return (
                  <linearGradient
                    key={endpoint}
                    id={`gradient-${index}`}
                    x1="0"
                    y1="0"
                    x2="0"
                    y2="1">
                    <stop offset="5%" stopColor={color} stopOpacity={0.8} />
                    <stop offset="95%" stopColor={color} stopOpacity={0.1} />
                  </linearGradient>
                );
              })}
            </defs>
            <CartesianGrid vertical={false} />
            <XAxis
              dataKey="date"
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              minTickGap={32}
              tickFormatter={(value) => {
                const date = new Date(value);
                return date.toLocaleDateString("en-US", {
                  month: "short",
                  day: "numeric",
                });
              }}
            />
            <ChartTooltip
              cursor={false}
              content={
                <ChartTooltipContent
                  labelFormatter={(value) => {
                    return new Date(value).toLocaleDateString("en-US", {
                      month: "short",
                      day: "numeric",
                    });
                  }}
                  indicator="dot"
                />
              }
            />
            {endpoints.map((endpoint, index) => (
              <Area
                key={endpoint}
                dataKey={endpoint}
                type="natural"
                fill={`url(#gradient-${index})`}
                stroke={generateColor(index)}
                stackId="a"
              />
            ))}
            <ChartLegend content={<ChartLegendContent />} />
          </AreaChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
