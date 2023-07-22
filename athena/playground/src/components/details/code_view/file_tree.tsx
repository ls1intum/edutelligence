import { FileTree } from "@/helpers/fetch_and_unzip";

type FileTreeProps = {
  tree: FileTree[];
  selectedFile?: string;
  onSelectFile: (path: string) => void;
  level?: number;
};

export default function FileTree({
  tree,
  selectedFile,
  onSelectFile,
  level = 0,
}: FileTreeProps) {
  return (
    <ul>
      {tree.map((file, index) =>
        file.dir ? (
          <li key={index} className={level === 0 ? "pl-2" : ""}>
            {file.dirname}/
            {file.children && (
              <FileTree
                tree={file.children}
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
              } hover:text-primary-500 hover:bg-gray-100 rounded-md w-full flex items-center justify-start pl-2`}
              onClick={() => onSelectFile(file.path)}
            >
              {file.filename}
            </button>
          </li>
        )
      )}
    </ul>
  );
}