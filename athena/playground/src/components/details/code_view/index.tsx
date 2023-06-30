import { useFetchAndUnzip } from "@/helpers/fetch_and_unzip";

import FileTree from "./file_tree";

type CodeViewProps = {
  repository_url: string;
};

export default function CodeView({ repository_url }: CodeViewProps) {
  const repository = useFetchAndUnzip(repository_url);

  return <FileTree tree={repository.tree} />;
}