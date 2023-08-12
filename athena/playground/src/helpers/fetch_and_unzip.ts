import { useEffect, useState } from "react";
import JSZip from "jszip";

export type FileTree = {
  path: string;
} & (
  | {
      isDir: false;
      filename: string;
    }
  | {
      isDir: true;
      dirname: string;
      children: FileTree[];
    }
);

function findSubPaths(paths: string[], path: string) {
  var rePath = path.replace("/", "\\/");
  var re = new RegExp("^" + rePath + "[^\\/]*\\/?$");
  const result = paths.filter(function (i) {
    return i !== path && re.test(i);
  });
  return result;
}

function buildFileTree(paths: string[], path: string = ""): FileTree[] {
  var tree: FileTree[] = [];

  findSubPaths(paths, path).forEach(function (subPath) {
    // All subPaths are prefixed with {path}*
    var remainingPath = subPath.replace(path, "");

    var promisses: Promise<FileTree>[] = [];

    // If there is no / in remainingPath, then it is a file
    if (remainingPath.indexOf("/") === -1) {
      tree.push({
        isDir: false,
        filename: remainingPath,
        path: path + remainingPath,
      });
    } else {
      // Else, it is a directory
      tree.push({
        isDir: true,
        dirname: remainingPath.replace("/", ""),
        path: path + remainingPath,
        children: buildFileTree(paths, path + remainingPath),
      });
    }
  });

  return tree;
}

export const useFetchAndUnzip = (url: string): { zip: JSZip, tree: FileTree[] } => {
  const [zip, setZip] = useState<JSZip>(new JSZip());
  const [tree, setTree] = useState<FileTree[]>([]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch(url);
        const blob = await response.blob();
        const zip = await JSZip.loadAsync(blob);
        const tree = buildFileTree(Object.keys(zip.files));

        setZip(zip);
        setTree(tree);
      } catch (error) {
        console.error("Error fetching or unzipping the file", error);
      }
    };

    fetchData();
  }, [url]);

  return { zip, tree };
};
