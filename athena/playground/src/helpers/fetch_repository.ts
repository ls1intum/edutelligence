/**
 * Repository fetching utilities for the playground.
 * Handles fetching repository filemaps and building file trees for display.
 */

import { useEffect, useMemo, useState } from "react";

export type FileTree =
  | {
      isDir: false;
      path: string;
      filename: string;
    }
  | {
      isDir: true;
      path: string;
      dirname: string;
      children: FileTree[];
    };

// Internal node shape for building the tree efficiently
type DirNode = {
  children: Map<string, DirNode | "file">;
};

function compareEntries(
  a: [string, DirNode | "file"],
  b: [string, DirNode | "file"]
) {
  const [nameA, childA] = a;
  const [nameB, childB] = b;

  const isDirA = childA !== "file";
  const isDirB = childB !== "file";

  if (isDirA !== isDirB) return isDirA ? -1 : 1; // dirs first
  return nameA.localeCompare(nameB);             // then A–Z
}


function buildFileTree(paths: string[]): FileTree[] {
  const root: DirNode = { children: new Map() };

  // Insert each file path into a trie
  for (const fullPath of paths) {
    const parts = fullPath.split("/").filter(Boolean);
    let node = root;

    parts.forEach((part, i) => {
      const isLast = i === parts.length - 1;

      if (isLast) {
        node.children.set(part, "file");
        return;
      }

      const existing = node.children.get(part);
      if (existing && existing !== "file") {
        node = existing;
      } else {
        const next: DirNode = { children: new Map() };
        node.children.set(part, next);
        node = next;
      }
    });
  }

  // Convert trie to FileTree recursively
  const toFileTree = (node: DirNode, basePath: string): FileTree[] => {
    const entries = Array.from(node.children.entries()).sort(compareEntries);

    const result: FileTree[] = [];
    for (const [name, child] of entries) {
      if (child === "file") {
        result.push({
          isDir: false as const,
          filename: name,
          path: basePath + name,
        });
      } else {
        const dirPath = basePath + name + "/";
        result.push({
          isDir: true as const,
          dirname: name,
          path: dirPath,
          children: toFileTree(child, dirPath),
        });
      }
    }
    return result;
  };

  return toFileTree(root, "");
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)
  );
}

export const useFetchFilemap = (url: string) => {
  const [isError, setIsError] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [filesMap, setFilesMap] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!url) return;

    const controller = new AbortController();

    (async () => {
      setIsLoading(true);
      setIsError(false);

      try {
        const response = await fetch(url, { signal: controller.signal });
        const data = await response.json();

        if (!response.ok || !isPlainRecord(data)) {
          throw new Error("Invalid repository filemap response");
        }

        // Validate values are strings
        const normalized: Record<string, string> = {};
        for (const [k, v] of Object.entries(data)) {
          if (typeof v === "string") normalized[k] = v;
        }

        setFilesMap(normalized);
      } catch (err) {
        if ((err as any)?.name !== "AbortError") {
          console.error("Error fetching repository filemap:", err);
          setIsError(true);
        }
      } finally {
        setIsLoading(false);
      }
    })();

    return () => controller.abort();
  }, [url]);

  // derive tree from filesMap to avoid storing redundant state
  const tree = useMemo(
    () => buildFileTree(Object.keys(filesMap)),
    [filesMap]
  );

  return { isLoading, isError, filesMap, tree };
};
