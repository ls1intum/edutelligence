"use client";

import { DateRangePicker } from "@components/custom/DateRangePicker";
import { ServiceSelect } from "@components/custom/ServiceSelect";

const services = ["Service A", "Service B"];

export function Menu() {
  return (
    <div className="grid auto-cols-max grid-flow-col justify-end gap-5 pb-5">
      <ServiceSelect selectedService={services[0]} services={services} />
      <DateRangePicker />
    </div>
  );
}
