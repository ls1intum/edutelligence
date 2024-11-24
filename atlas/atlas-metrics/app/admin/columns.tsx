"use client"

import {ColumnDef} from "@tanstack/table-core";
import {RawEndpointActivityDAO} from "@/app/domain/dao/endpointActivity";
import {DataTableColumnHeader} from "@/components/custom/data-table-column-header";

export const endpointActivityColumns: ColumnDef<RawEndpointActivityDAO>[] = [
    {
        accessorKey: "date",
        header: ({ column }) => (
            <DataTableColumnHeader column={column} title="Timestamp" />
        ),
        cell: ({ row }) => {
            const date = new Date(row.getValue("date"));
            return <div className="text-left">{date.toLocaleString()}</div>
        },
    },
    {
        accessorKey: "endpoint",
        header: ({ column }) => (
            <DataTableColumnHeader column={column} title="Endpoint" />
        ),
        cell: ({ row }) => {
            return <div className="text-left">{row.getValue("endpoint")}</div>
        },
    },
]