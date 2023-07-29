import type { Feedback } from "@/model/feedback";

import { useEffect, useState } from "react";
import { Allotment } from "allotment";

import { useFetchAndUnzip } from "@/helpers/fetch_and_unzip";

import FileTree from "./file_tree";
import FileEditor from "./file_editor";

type CodeEditorProps = {
  repository_url: string;
  feedbacks?: Feedback[];
  onFeedbacksChange?: (feedback: Feedback[]) => void;
  createNewFeedback?: () => Feedback;
};

export default function CodeEditor({
  repository_url,
  feedbacks,
  onFeedbacksChange,
  createNewFeedback,
}: CodeEditorProps) {
  const repository = useFetchAndUnzip(repository_url);
  const [selectedFile, setSelectedFile] = useState<string | undefined>(
    undefined
  );
  const [fileContent, setFileContent] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (selectedFile && repository) {
      repository.zip
        .file(selectedFile)
        ?.async("string")
        .then(setFileContent)
        .catch(console.error);
    }
  }, [selectedFile, repository]);

  return (
    <div className="h-[50vh] border border-gray-100 rounded-lg overflow-hidden">
      <Allotment vertical={false} defaultSizes={[1, 4]}>
        <Allotment.Pane preferredSize={"20%"}>
          <FileTree
            tree={repository.tree}
            feedbacks={feedbacks}
            selectedFile={selectedFile}
            onSelectFile={setSelectedFile}
          />
        </Allotment.Pane>
        <Allotment.Pane>
          {fileContent ? (
            <div className="h-full w-full">
              <div className="text-gray-500 text-sm py-0.5 px-2 bg-gray-50 italic">
                {selectedFile}
              </div>
              <FileEditor
                content={fileContent}
                identifier={repository_url}
                filePath={selectedFile}
                feedbacks={feedbacks}
                onFeedbacksChange={onFeedbacksChange}
                createNewFeedback={createNewFeedback}
              />
            </div>
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
