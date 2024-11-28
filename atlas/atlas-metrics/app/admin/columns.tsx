"use client";

import { ColumnDef } from "@tanstack/table-core";
import { EndpointActivityDAO } from "@/app/domain/dao/endpointActivity";
import { DataTableColumnHeader } from "@/components/custom/DataTableColumnHeader";
import { useEffect, useState } from "react";

export const endpointActivityColumns: ColumnDef<EndpointActivityDAO>[] = [
  {
    accessorKey: "date",
    header: ({ column }) => <DataTableColumnHeader column={column} title="Timestamp" />,
    cell: ({ row }) => {
      // eslint-disable-next-line react-hooks/rules-of-hooks
      const [date, setDate] = useState("");
      // eslint-disable-next-line react-hooks/rules-of-hooks
      useEffect(() => {
        const d = row.getValue("date") as Date;
        setDate(d.toLocaleString());
      }, [row]);
      return <div className="text-left">{date}</div>;
    },
  },
  {
    accessorKey: "service",
    header: ({ column }) => <DataTableColumnHeader column={column} title="Service" />,
    cell: ({ row }) => {
      return <div className="text-center">{row.getValue("service")}</div>;
    },
  },
  {
    accessorKey: "version",
    header: ({ column }) => <DataTableColumnHeader column={column} title="Version" />,
    cell: ({ row }) => {
      return <div className="text-center">{row.getValue("version")}</div>;
    },
  },
  {
    accessorKey: "endpoint",
    header: ({ column }) => <DataTableColumnHeader column={column} title="Endpoint" />,
    cell: ({ row }) => {
      return <div className="text-left">{row.getValue("endpoint")}</div>;
    },
  },
  {
    accessorKey: "type",
    header: ({ column }) => <DataTableColumnHeader column={column} title="RequestType" />,
    cell: ({ row }) => {
      return <div className="text-center">{row.getValue("type")}</div>;
    },
  },
];
