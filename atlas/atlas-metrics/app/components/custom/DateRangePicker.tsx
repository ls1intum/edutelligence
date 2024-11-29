"use client";

import * as React from "react";
import { subMonths, format } from "date-fns";
import { Calendar as CalendarIcon } from "lucide-react";
import { DateRange } from "react-day-picker";

import { cn } from "@lib/utils";
import { Button } from "@components/ui/button";
import { Calendar } from "@components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@components/ui/popover";
import { useRouter, useSearchParams } from "next/navigation";

export function DateRangePicker({ className }: React.HTMLAttributes<HTMLDivElement>) {
  const router = useRouter();

  const setQueryParams = (from?: Date, to?: Date) => {
    const params = new URLSearchParams(window.location.search);
    if (from) {
      params.set("from", from.toISOString());
    }
    if (to) {
      params.set("to", to.toISOString());
    }
    router.push(`${window.location.pathname}?${params.toString()}`);
  };

  const searchParams = useSearchParams();
  const initFrom = searchParams.get("from")
    ? new Date(searchParams.get("from") as string)
    : subMonths(new Date(), 1);
  const initTo = searchParams.get("to") ? new Date(searchParams.get("to") as string) : new Date();

  const [date, setDate] = React.useState<DateRange | undefined>({
    from: initFrom,
    to: initTo,
  });

  const handleSelect = (range: DateRange | undefined) => {
    setDate(range);
    if (range?.from && range?.to) {
      setQueryParams(range.from, range.to);
    }
  };

  return (
    <div className={cn("grid gap-2", className)}>
      <Popover>
        <PopoverTrigger asChild>
          <Button
            id="date"
            variant="outline"
            className={cn(
              "w-[300px] justify-start text-left font-normal",
              !date && "text-muted-foreground",
            )}>
            <CalendarIcon />
            {date?.from ? (
              date.to ? (
                <>
                  {format(date.from, "LLL dd, y")} - {format(date.to, "LLL dd, y")}
                </>
              ) : (
                format(date.from, "LLL dd, y")
              )
            ) : (
              <span>Pick a date</span>
            )}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0" align="start">
          <Calendar
            initialFocus
            mode="range"
            defaultMonth={date?.from}
            selected={date}
            onSelect={handleSelect}
            numberOfMonths={2}
          />
        </PopoverContent>
      </Popover>
    </div>
  );
}
