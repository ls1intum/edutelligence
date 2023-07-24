import { useFetchAndUnzip } from "@/helpers/fetch_and_unzip";

import FileTree from "./file_tree";

export default function CodeView({ repository_url }: { repository_url: string; }) {
  const repository = useFetchAndUnzip(repository_url);

  return <FileTree tree={repository.tree} />;
}