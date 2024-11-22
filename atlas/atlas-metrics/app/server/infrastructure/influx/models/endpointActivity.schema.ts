import { z } from "zod";
import {RawEndpointActivityDAO} from "@/app/domain/dao/endpointActivity";

export const validateEndpointActivitySchema = (data: unknown[]): RawEndpointActivityDAO[] => {
    return data.map((row, index) => {
        const parsed = EndpointActivitySchema.safeParse(row);

        if (!parsed.success) {
            throw new Error(`Invalid data format in endpoint_activity row ${index}: ${parsed.error}`);
        }

        const { endpoint, _time } = parsed.data;

        return {
            endpoint: endpoint,
            date: _time
        };
    });
}

const EndpointActivitySchema = z.object({
    endpoint: z.string(),
    _time: z.date(),
});