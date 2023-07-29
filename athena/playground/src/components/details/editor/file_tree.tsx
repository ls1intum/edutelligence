import type { Feedback } from "@/model/feedback";

import { FileTree } from "@/helpers/fetch_and_unzip";
import { twMerge } from "tailwind-merge";

import { renderers as bpRenderers } from "react-complex-tree-blueprintjs-renderers";
import { StaticTreeDataProvider, Tree, UncontrolledTreeEnvironment } from "react-complex-tree";
import { FocusStyleManager } from "@blueprintjs/core";

type FileTreeProps = {
  tree: FileTree[];
  feedbacks?: Feedback[];
  selectedFile?: string;
  onSelectFile: (path: string) => void;
};

export default function FileTree({
  tree,
  feedbacks,
  selectedFile,
  onSelectFile,
}: FileTreeProps) {
  const items = {
    root: {
      index: "root",
      isFolder: true,
      children: ["child1", "child2"],
      data: "Root item",
    },
    child1: {
      index: "child1",
      children: [],
      data: "Child item 1",
    },
    child2: {
      index: "child2",
      isFolder: true,
      children: ["child3"],
      data: "Child item 2",
    },
    child3: {
      index: "child3",
      children: [],
      data: "Child item 3",
    },
  };

  return (
    <div 
      onMouseDown={() => FocusStyleManager.onlyShowFocusOnTabs()}
      onKeyDown={() => FocusStyleManager.alwaysShowFocus()}
    >
    <UncontrolledTreeEnvironment
      {...bpRenderers}
      dataProvider={new StaticTreeDataProvider(items, (item, data) => ({ ...item, data }))}
      getItemTitle={item => item.data}
      viewState={{}}
    >
      <Tree treeId="tree-1" rootItem="root" treeLabel="Tree Example" />
    </UncontrolledTreeEnvironment>
    </div>
  );
}

// export default function FileTree({
//   tree,
//   feedbacks,
//   selectedFile,
//   onSelectFile,
//   level = 0,
// }: FileTreeProps) {

//   const getFeedbackIndicator = (path: string) => {
//     const feedbackCount = feedbacks?.filter((feedback) => "file_path" in feedback && feedback.file_path === path).length ?? 0;
//     if (feedbackCount === 0) return null;
//     return <span className="ml-1 text-indigo-500 rounded-full bg-indigo-100 text-xs px-2 py-0.5
//     ">{feedbackCount}</span>;
//   };

//   return (
//     <ul className={twMerge("text-xs", level > 0 ? "border-l border-gray-100" : "")}>
//       {tree.map((file, index) =>
//         file.dir ? (
//           <li key={index} className={level > 0 ? "pl-2" : ""}>
//             {file.dirname}/
//             {file.children && (
//               <FileTree
//                 tree={file.children}
//                 feedbacks={feedbacks}
//                 selectedFile={selectedFile}
//                 onSelectFile={onSelectFile}
//                 level={level + 1}
//               />
//             )}
//           </li>
//         ) : (
//           <li key={index} className={level > 0 ? "pl-2" : ""}>
//             <button
//               className={`${
//                 selectedFile === file.path
//                   ? "text-primary-500"
//                   : "text-gray-500"
//               } hover:text-primary-500 hover:bg-gray-100 rounded-md w-full flex items-center justify-between`}
//               onClick={() => onSelectFile(file.path)}
//             >
//               {file.filename}
//               {getFeedbackIndicator(file.path)}
//             </button>
//           </li>
//         )
//       )}
//     </ul>
//   );
// }
