import type { Feedback } from "@/model/feedback";
import type { FileTree } from "@/helpers/fetch_repository";

import { useId, useState } from "react";
import {
  ControlledTreeEnvironment,
  Tree,
  TreeItem,
  TreeItemIndex,
} from "react-complex-tree";
import { twMerge } from "tailwind-merge";

type FileTreeProps = {
  tree: FileTree[];
  feedbacks?: Feedback[];
  selectedFile?: string;
  onSelectFile: (path: string) => void;
};

type ItemData = {
  path: string;
  name: string;
  isDir: boolean;
  feedbackCount?: number;
};

export default function FileTree({
  tree,
  feedbacks,
  onSelectFile,
}: FileTreeProps) {
  const treeId = useId();

  let items: { [index: string]: TreeItem<ItemData> } = {
    root: {
      index: "root",
      isFolder: true,
      children: tree.map((file) => file.path),
      data: {
        path: "/",
        name: "Root Item",
        isDir: true,
      },
    },
  };

  const addChildren = (item: FileTree): number => {
    if (item.isDir) {
      const feedbackCount = item.children.reduce(
        (acc, file) => acc + (addChildren(file) ?? 0),
        0
      );
      items[item.path] = {
        index: item.path,
        isFolder: true,
        children: item.children?.map((file) => file.path) ?? [],
        data: {
          path: item.path,
          name: item.dirname,
          isDir: true,
          feedbackCount: feedbackCount > 0 ? feedbackCount : undefined,
        },
      };
      return feedbackCount;
    } else {
      const feedbackCount =
        feedbacks?.filter(
          (feedback) =>
            "file_path" in feedback && feedback.file_path === item.path
        ).length ?? 0;
      items[item.path] = {
        index: item.path,
        children: [],
        data: {
          path: item.path,
          name: item.filename,
          isDir: false,
          feedbackCount: feedbackCount > 0 ? feedbackCount : undefined,
        },
      };
      return feedbackCount;
    }
  };
  tree.forEach(addChildren);

  const [focusedItem, setFocusedItem] = useState<TreeItemIndex>();
  const [expandedItems, setExpandedItems] = useState<TreeItemIndex[]>([]);
  const [selectedItems, setSelectedItems] = useState<TreeItemIndex[]>([]);

  return (
    <div className="h-full overflow-auto focus-visible:outline-hidden">
      <ControlledTreeEnvironment<ItemData>
        items={items}
        getItemTitle={(item) => item.data.name}
        viewState={{
          [treeId]: {
            focusedItem,
            expandedItems,
            selectedItems,
          },
        }}
        onFocusItem={(item) => setFocusedItem(item.index)}
        onExpandItem={(item) =>
          setExpandedItems([...expandedItems, item.index])
        }
        onCollapseItem={(item) =>
          setExpandedItems(
            expandedItems.filter(
              (expandedItemIndex) => expandedItemIndex !== item.index
            )
          )
        }
        onSelectItems={(items) => setSelectedItems(items)}
        onPrimaryAction={(item) => onSelectFile(`${item.index}`)}
        renderItemTitle={({ item, context }) => (
          <span className="flex items-center gap-1">
            <span>{item.data.name}</span>
            {item.data.feedbackCount && (
              <span
                className={twMerge(
                  "px-1 py-0.5 text-xs",
                  item.data.isDir
                    ? "rounded-full text-slate-500"
                    : "rounded-sm text-blue-800 bg-blue-200",
                  context.isSelected && item.data.isDir ? "text-white" : ""
                )}
              >
                {item.data.feedbackCount}
              </span>
            )}
          </span>
        )}
      >
        <Tree treeId={treeId} rootItem="root" treeLabel="File Tree" />
      </ControlledTreeEnvironment>
    </div>
  );
}
