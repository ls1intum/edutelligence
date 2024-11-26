import {RequestType} from "@/app/domain/dao/RequestTypes";
import {z} from "zod";
import {z_stringOrDateToDate} from "@/lib/zod-utils";

export type EndpointActivityDAO = {
    endpoint: string;
    date: Date;
    type: RequestType
};

export const EndpointActivitySchema = z.object({
    endpoint: z.string(),
    type: z.nativeEnum(RequestType),
    _time: z_stringOrDateToDate,
});

export type EndpointActivityFullDAO = EndpointActivityDAO & {
    service: string;
    version: string;
};

export const EndpointActivityFullSchema = z.object({
    service: z.string(),
    version: z.string(),
    endpoint: z.string(),
    type: z.nativeEnum(RequestType),
    date: z_stringOrDateToDate,
});