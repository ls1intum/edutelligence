"use client";

import { DateRangePicker } from "@components/custom/DateRangePicker";
import { ServiceSelect } from "@components/custom/ServiceSelect";

interface MenuProps {
  selectedService?: string;
  services: string[];
}

export function Menu({ selectedService, services }: MenuProps) {
  return (
    <div className="grid auto-cols-max grid-flow-col justify-end gap-5 pb-5">
      <ServiceSelect selectedService={selectedService} services={services} />
      <DateRangePicker />
    </div>
  );
}
