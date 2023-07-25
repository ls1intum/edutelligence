import type { Feedback } from "@/model/feedback";

import { FileTree } from "@/helpers/fetch_and_unzip";

type FileTreeProps = {
  tree: FileTree[];
  feedbacks?: Feedback[];
  selectedFile?: string;
  onSelectFile: (path: string) => void;
  level?: number;
};

export default function FileTree({
  tree,
  feedbacks,
  selectedFile,
  onSelectFile,
  level = 0,
}: FileTreeProps) {

  const getFeedbackIndicator = (path: string) => {
    const feedbackCount = feedbacks?.filter((feedback) => "file_path" in feedback && feedback.file_path === path).length ?? 0;
    if (feedbackCount === 0) return null;
    return <span className="ml-1 text-indigo-500 rounded-full bg-indigo-100 text-xs px-2 py-0.5
    ">{feedbackCount}</span>;
  };

  return (
    <ul>
      {tree.map((file, index) =>
        file.dir ? (
          <li key={index} className={level === 0 ? "pl-2" : ""}>
            {file.dirname}/
            {file.children && (
              <FileTree
                tree={file.children}
                feedbacks={feedbacks}
                selectedFile={selectedFile}
                onSelectFile={onSelectFile}
                level={level + 1}
              />
            )}
          </li>
        ) : (
          <li key={index}>
            <button
              className={`${
                selectedFile === file.path
                  ? "text-primary-500"
                  : "text-gray-500"
              } hover:text-primary-500 hover:bg-gray-100 rounded-md w-full flex items-center pl-2 justify-between`}
              onClick={() => onSelectFile(file.path)}
            >
              {file.filename} 
              {getFeedbackIndicator(file.path)}
            </button>
          </li>
        )
      )}
    </ul>
  );
}