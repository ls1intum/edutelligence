import { z } from "zod";
import {EndpointActivityFullDAO} from "@/app/domain/dao/endpointActivity";
import {RequestType} from "@/app/domain/dao/RequestTypes";
import {z_stringOrDateToDate} from "@/lib/zod-utils";

export const validateEndpointActivitySchema = (data: unknown[]): EndpointActivityFullDAO[] => {
    return data.map((row, index) => {
        const parsed = EndpointActivitySchema.safeParse(row);

        if (!parsed.success) {
            throw new Error(`Invalid data format in endpoint_activity row ${index}: ${parsed.error}`);
        }

        const {service, version, endpoint, type, _time } = parsed.data;

        return {
            service: service,
            version: version,
            endpoint: endpoint,
            type: type,
            date: _time
        };
    });
}

const EndpointActivitySchema = z.object({
    service: z.string(),
    version: z.string(),
    endpoint: z.string(),
    type: z.nativeEnum(RequestType),
    _time: z_stringOrDateToDate,
});