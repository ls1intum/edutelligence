"use client"

import * as React from "react"
import { TrendingUp } from "lucide-react"
import { Label, Pie, PieChart } from "recharts"

import {
    Card,
    CardContent,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle,
} from "@/components/ui/card"
import {
    ChartConfig,
    ChartContainer,
    ChartLegend,
    ChartLegendContent,
    ChartTooltip,
    ChartTooltipContent,
} from "@/components/ui/chart"
import {PieChartDataItemDAO} from "@/app/domain/dao/pieChartDataItem";
import {generateColor} from "@/lib/utils";

interface PieChartProps {
    title: string
    description: string
    label: string
    chartData: PieChartDataItemDAO[]
}

function generateChartConfig(chartData: PieChartDataItemDAO[]): ChartConfig {
    const labels = chartData.map((item) => item.label);
    const chartConfig: ChartConfig = {};

    labels.forEach((label, index) => {
        chartConfig[label] = {
            label: label,
            color: generateColor(index),
        };
    });
    return chartConfig;
}

function augmentColorInChartData(chartConfig: ChartConfig, chartData: PieChartDataItemDAO[]): PieChartDataItemDAO[] {
    return chartData.map((item) => {
        const color = chartConfig[item.label].color;
        return {...item, fill: color};
    });

}

export function PieChartDonut({title, description, label, chartData}: PieChartProps) {
    const total = React.useMemo(() => {
        return chartData.reduce((acc, curr) => acc + curr.value, 0)
    }, [chartData])

    const chartConfig = generateChartConfig(chartData);
    const chartDataAugmented = augmentColorInChartData(chartConfig, chartData);
    console.log(chartDataAugmented);

    return (
        <Card className="flex flex-col">
            <CardHeader className="items-center pb-0">
                <CardTitle>{title}</CardTitle>
                <CardDescription>{description}</CardDescription>
            </CardHeader>
            <CardContent className="flex-1 pb-0">
                <ChartContainer
                    config={chartConfig}
                    className="mx-auto aspect-square max-h-[250px]"
                >
                    <PieChart>
                        <ChartTooltip
                            cursor={false}
                            content={<ChartTooltipContent hideLabel />}
                        />
                        <Pie
                            data={chartDataAugmented}
                            dataKey="value"
                            nameKey="label"
                            innerRadius={60}
                            strokeWidth={5}
                        >
                            <Label
                                content={({ viewBox }) => {
                                    if (viewBox && "cx" in viewBox && "cy" in viewBox) {
                                        return (
                                            <text
                                                x={viewBox.cx}
                                                y={viewBox.cy}
                                                textAnchor="middle"
                                                dominantBaseline="middle"
                                            >
                                                <tspan
                                                    x={viewBox.cx}
                                                    y={viewBox.cy}
                                                    className="fill-foreground text-3xl font-bold"
                                                >
                                                    {total.toLocaleString()}
                                                </tspan>
                                                <tspan
                                                    x={viewBox.cx}
                                                    y={(viewBox.cy || 0) + 24}
                                                    className="fill-muted-foreground"
                                                >
                                                    {label}
                                                </tspan>
                                            </text>
                                        )
                                    }
                                }}
                            />
                        </Pie>
                        <ChartLegend
                            content={<ChartLegendContent nameKey="label" />}
                            className="-translate-y-2 flex-wrap gap-2 [&>*]:basis-1/4 [&>*]:justify-center"
                        />
                    </PieChart>
                </ChartContainer>
            </CardContent>
        </Card>
    )
}
