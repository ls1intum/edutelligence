"use client"

import {Button} from "@/components/ui/button";
import {ArrowUpDown} from "lucide-react";
import {Column} from "@tanstack/table-core";

interface DataTableColumnHeaderProps<TData> {
    column: Column<TData>;
    title: string;
}

export function DataTableColumnHeader<TData>({column, title} : DataTableColumnHeaderProps<TData>) {
    return (
        <Button
            variant="ghost"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
        >
            {title}
            <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
    )
}