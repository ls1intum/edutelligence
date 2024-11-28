"use client";

import { DateRangePicker } from "@components/custom/DateRangePicker";

export function Menu() {
  return (
    <div className="grid auto-cols-max grid-flow-col justify-end gap-5 pb-5">
      <DateRangePicker />
    </div>
  );
}
