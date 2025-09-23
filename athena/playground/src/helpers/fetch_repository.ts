/**
 * Repository fetching utilities for the playground.
 * Handles fetching repository filemaps and building file trees for display.
 */

import { useEffect, useState } from "react";

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


export const useFetchFilemap = (url: string) => {
  const [isError, setIsError] = useState<boolean>(false);
  const [filesMap, setFilesMap] = useState<Record<string, string>>({});
  const [tree, setTree] = useState<FileTree[]>([]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch(url);
        const data = await response.json();
        
        if (!response.ok || typeof data !== 'object') {
          throw new Error('Invalid repository filemap response');
        }
        
        setFilesMap(data);
        setTree(buildFileTree(Object.keys(data)));
        setIsError(false);
      } catch (error) {
        console.error('Error fetching repository filemap:', error);
        setIsError(true);
      }
    };

    fetchData();
  }, [url]);

  return { isError, filesMap, tree };
};