import Health from "@/pages/components/health";

export default function AthenaUrlInput(
    {value, onChange}: { value: string, onChange: (value: string) => void}
) {
    return (
        <div className="bg-white rounded-md p-4">
            <label className="flex flex-col">
                <span className="text-lg font-bold">Athena URL</span>
                <input className="border border-gray-300 rounded-md p-2" value={value} onChange={e => onChange(e.target.value)}/>
            </label>
            <Health url={value} />
        </div>
    );
}