import {DateRangePicker} from "@/components/custom/date-range-picker";

export function Menu() {
    return (
        <div className="grid grid-flow-col auto-cols-max gap-5 justify-end pb-5">
            <DateRangePicker/>
        </div>
    );
}