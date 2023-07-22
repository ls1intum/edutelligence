import { useState } from "react";
import { Allotment } from "allotment";

import { useFetchAndUnzip } from "@/helpers/fetch_and_unzip";

import FileTree from "./file_tree";

type CodeViewProps = {
  repository_url: string;
};

export default function CodeView({ repository_url }: CodeViewProps) {
  const repository = useFetchAndUnzip(repository_url);
  const [selectedFile, setSelectedFile] = useState<string | undefined>(undefined);

  return <Allotment vertical={false} defaultSizes={[1, 4]}>
  <Allotment.Pane preferredSize={"20%"}>
    <div className="h-full overflow-y-auto mr-2">
      <FileTree
        tree={repository.tree}
        selectedFile={selectedFile}
        onSelectFile={setSelectedFile}
      />
    </div>
  </Allotment.Pane>
  </Allotment>
}