import { FileTree } from "@/helpers/fetch_and_unzip";

export default function FileTree({ tree }: { tree: FileTree[] }) {
  return (
    <ul>
      {tree.map((file, index) => (
        <li key={index} className="ml-2">
          {file.dir ? (
            <>
              {file.dirname}
              {file.children && <FileTree tree={file.children} />}
            </>
          ) : (
            file.filename
          )}
        </li>
      ))}
    </ul>
  );
}
