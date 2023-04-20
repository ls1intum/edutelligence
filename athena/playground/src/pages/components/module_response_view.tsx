import ModuleResponse from "@/pages/model/module_response";


export default function ModuleResponseView(
    {response}: { response: ModuleResponse | undefined }
) {
    if (!response) {
        return null;
    }
    let formattedData = response.data;
    try {
        formattedData = JSON.parse(formattedData);
    } catch (e) {
        // ignore
    }
    if (typeof formattedData === "object") {
        formattedData = JSON.stringify(formattedData, null, 2);
    }
    // show response.module_name and the formattedData
    return (
        <div className="flex flex-col">
            <h2 className="text-2xl font-bold mb-4">
                Response
            </h2>
            <div className="flex flex-col">
                <span className="font-bold mb-4">
                    Used module:
                </span>
                <span className="mb-4">
                    {response.module_name}
                </span>
            </div>
            <div className="flex flex-col">
                <span className="font-bold mb-4">
                    Status code:
                </span>
                <span className="mb-4">
                    {response.status}
                </span>
            </div>
            <div className="flex flex-col">
                <span className="font-bold mb-4">
                    Data:
                </span>
                <pre className="mb-4 bg-gray-100 p-4 rounded-md overflow-x-auto">
                    {formattedData}
                </pre>
            </div>
        </div>
    );
}
