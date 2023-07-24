import { useEffect, useState } from "react";
import { Allotment } from "allotment";

import { useFetchAndUnzip } from "@/helpers/fetch_and_unzip";

import FileTree from "./file_tree";
import FileEditor from "./file_editor";

type CodeViewProps = {
  repository_url: string;
};

export default function CodeView({ repository_url }: CodeViewProps) {
  const repository = useFetchAndUnzip(repository_url);
  const [selectedFile, setSelectedFile] = useState<string | undefined>(
    undefined
  );
  const [fileContent, setFileContent] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (selectedFile) {
      repository.zip.file(selectedFile)?.async("string").then(setFileContent);
    }
  }, [selectedFile, repository]);

  return (
    <div className="h-[40vh]">
      <Allotment vertical={false} defaultSizes={[1, 4]}>
        <Allotment.Pane preferredSize={"20%"}>
          <div className="h-full overflow-y-auto mr-2">
            <FileTree
              tree={repository.tree}
              selectedFile={selectedFile}
              onSelectFile={setSelectedFile}
            />
          </div>
        </Allotment.Pane>
        <Allotment.Pane>
          {fileContent ? (
            <FileEditor
              type="programming"
              content={fileContent}
              filePath={selectedFile}
              feedbacks={undefined}
              onFeedbacksChange={() => undefined}
            />
          ) : (
            <div className="h-full w-full flex items-center justify-center">
              <p className="text-gray-500">Select a file to view its content</p>
            </div>
          )}
        </Allotment.Pane>
      </Allotment>
    </div>
  );
}
