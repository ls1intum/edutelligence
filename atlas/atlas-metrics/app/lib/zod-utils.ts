import { z } from "zod";

export const z_stringOrDateToDate = z
  .string()
  .or(z.date())
  .transform((arg) => new Date(arg));
