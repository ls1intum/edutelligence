import { z } from "zod";

export const validateServiceSchema = (data: unknown[]): string[] => {
  return data.map((row, index) => {
    const parsed = ServiceSchema.safeParse(row);

    if (!parsed.success) {
      throw new Error(`Invalid data format in service row ${index}: ${parsed.error}`);
    }

    const { service } = parsed.data;

    return service;
  });
};

const ServiceSchema = z.object({
  service: z.string(),
});
