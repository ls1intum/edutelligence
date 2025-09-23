import type { Feedback } from "@/model/feedback";
import type { ManualRating } from "@/model/manual_rating";

import { useEffect, useState } from "react";
import { Allotment } from "allotment";

import { useFetchFilemap } from "@/helpers/fetch_repository";

import FileTree from "./file_tree";
import FileEditor from "./file_editor";

type CodeEditorProps = {
  identifier?: string;
  repositoryUrl: string;
  feedbacks?: Feedback[];
  onFeedbacksChange?: (feedback: Feedback[]) => void;
  createNewFeedback?: () => Feedback;
  manualRatings?: ManualRating[];
  onManualRatingsChange?: (manualRatings: ManualRating[]) => void;
};

export default function CodeEditor({
  identifier,
  repositoryUrl,
  feedbacks,
  onFeedbacksChange,
  createNewFeedback,
  manualRatings,
  onManualRatingsChange,
}: CodeEditorProps) {
  const {
    isError,
    filesMap,
    tree,
  } = useFetchFilemap(repositoryUrl);
  const [selectedFile, setSelectedFile] = useState<string | undefined>(
    undefined
  );
  const [fileContent, setFileContent] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (selectedFile && filesMap) {
      setFileContent(filesMap[selectedFile] || undefined);
    }
  }, [selectedFile, filesMap]);

  if (isError) {
    return (
      <div className="text-red-500 text-sm">
        Failed to load repository, did you link the downloaded repositories?
        <div className="text-gray-500">
          <code>npm run export:artemis:4-link-programming-repositories</code>
        </div>
      </div>
    );
  }

  return (
    <div className="h-[60vh] border border-gray-100 rounded-lg overflow-hidden">
      <Allotment vertical={false} defaultSizes={[1, 4]}>
        <Allotment.Pane preferredSize={"20%"}>
          <FileTree
            tree={tree}
            feedbacks={feedbacks}
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
                identifier={
                  identifier
                    ? `${identifier}-${repositoryUrl}`
                    : repositoryUrl
                }
                filePath={selectedFile}
                feedbacks={feedbacks}
                onFeedbacksChange={onFeedbacksChange}
                createNewFeedback={createNewFeedback}
                manualRatings={manualRatings}
                onManualRatingsChange={onManualRatingsChange}
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
