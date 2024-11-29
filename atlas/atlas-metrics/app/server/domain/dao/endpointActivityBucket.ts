import { z } from "zod";
import { RequestType } from "@server/domain/dao/RequestTypes";
import { z_stringOrDateToDate } from "@lib/zod-utils";

export type EndpointActivityBucketDAO = {
  endpoint: string;
  type: RequestType;
  date: Date;
  count: number;
};

export const EndpointActivityBucketScheme = z.object({
  endpoint: z.string(),
  type: z.nativeEnum(RequestType),
  date: z_stringOrDateToDate,
  count: z.number(),
});
