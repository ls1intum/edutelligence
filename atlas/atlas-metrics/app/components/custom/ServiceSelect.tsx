import { useRouter } from "next/navigation";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@components/ui/select";

interface ServiceSelectProps {
  selectedService: string;
  services: string[];
}

export function ServiceSelect({ selectedService, services }: ServiceSelectProps) {
  const router = useRouter();

  const handleItemClick = (newService: string) => {
    const params = new URLSearchParams(window.location.search);
    params.set("service", newService);
    router.push(`${window.location.pathname}?${params.toString()}`);
  };

  return (
    <Select defaultValue={selectedService} onValueChange={(value) => handleItemClick(value)}>
      <SelectTrigger className="w-[180px]">
        <SelectValue placeholder="Select a service" />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          <SelectLabel>Service</SelectLabel>
          {services.map((service) => (
            <SelectItem key={service} value={service}>
              {service[0].toUpperCase() + service.slice(1)}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}
