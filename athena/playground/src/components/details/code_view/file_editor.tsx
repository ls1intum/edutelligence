import { Feedback, getFeedbackRange } from "@/model/feedback";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Monaco, Editor, useMonaco } from "@monaco-editor/react";
import { editor } from "monaco-editor";
import * as portals from 'react-reverse-portal';
import { createRoot } from "react-dom/client";

type FileEditorProps = {
  content: string;
  filePath?: string;
  feedbacks?: Feedback[];
  onFeedbackChange: (feedback: Feedback[]) => void;
};

const MyComponent = () => {
  const [count, setCount] = useState<number>(0);

  return <div>
  My first view zone {count}
  <br />
  <button onClick={() => {
    setCount(count + 1)
    console.log("Click")
  }}>Click me</button>
  </div>
}

export default function FileEditor({
  content,
  filePath,
  feedbacks,
  onFeedbackChange,
}: FileEditorProps) {
  const editorRef = useRef<editor.IStandaloneCodeEditor>();
  const monaco = useMonaco();

  const id = useId();
  const portalNodes = useMemo(() => feedbacks?.map(() => portals.createHtmlPortalNode()), [feedbacks]);
  const resizeObservers = useRef<(ResizeObserver | null)[]>([]);
  const [decorationsCollection, setDecorationsCollection] = useState<editor.IEditorDecorationsCollection | undefined>(undefined);

  useEffect(() => {
    if (monaco) {
      console.log('here is the monaco instance:', monaco);
      console.log('Models', monaco.editor.getModels())
      const path = monaco.Uri.parse(filePath || "")
      monaco.editor.getModel(path)?.dispose()
      console.log("Create model")
      const model = monaco.editor.createModel(content, undefined, path)
      editorRef.current?.setModel(model);
    }
  }, [monaco, filePath, content]);

  const handleEditorDidMount = (editor: editor.IStandaloneCodeEditor, monaco: Monaco) => {
    editorRef.current = editor;

    const feedbackRanges = feedbacks?.map(feedback => getFeedbackRange(content, feedback));

    let overlayNodes: HTMLDivElement[] = [];
    feedbacks?.forEach((_, index) => {
      const portalNode = portalNodes![index]!;

      const overlayNode = document.createElement("div");
      overlayNode.id = `feedback-${id}-${index}-overlay`;
      overlayNode.style.width = '100%';
      const root = createRoot(overlayNode);
      root.render(<portals.OutPortal node={portalNode} />);
    
      var overlayWidget = {
        getId: () => `feedback-${id}-${index}-widget`,
        getDomNode: () => overlayNode,
        getPosition: () => null,
      };
      editor.addOverlayWidget(overlayWidget);
      overlayNodes.push(overlayNode);
    })

    editor.changeViewZones(function (changeAccessor) {
      feedbacks?.forEach((_, index) => {
        const overlayNode = overlayNodes[index];
        const zoneNode = document.createElement("div");
        zoneNode.id = `feedback-${id}-${index}-zone`;

        const zoneId = changeAccessor.addZone({
          afterLineNumber: feedbackRanges![index]?.endLineNumber || Infinity,
          afterColumn: feedbackRanges![index]?.endColumn,
          domNode: zoneNode,
          get heightInPx() {
            return overlayNode.offsetHeight;
          },
          onDomNodeTop: top => {
            overlayNode.style.top = top + "px";
          },
        });
        const observer = new ResizeObserver(() => {
          editor.changeViewZones(accessor => accessor.layoutZone(zoneId));
        });
        observer.observe(overlayNode);
        resizeObservers.current.push(observer);
    }
    )});
    
    if (decorationsCollection) {
      decorationsCollection.clear();
    }
    console.log(feedbackRanges)
    const newDecorationsCollection = editor.createDecorationsCollection(
      feedbackRanges?.flatMap(range => (
        range ? [{
          options: {
            inlineClassName: "bg-primary-300 rounded-md py-1",
          },
          range,
        }] : [])) ?? []
    );
    setDecorationsCollection(newDecorationsCollection);
  }

  // Cleanup on unmount
  useEffect(() => {
    if (editorRef.current && monaco) {
      handleEditorDidMount(editorRef.current, monaco);
    }
    return () => {
      resizeObservers.current.forEach(observer => observer?.disconnect());
      resizeObservers.current = [];
    };
  }, []);

  return <div className="h-[50vh] hover:bg-primary-500">
  <Editor
    options={{
      automaticLayout: true,
      scrollbar: {
        vertical: "hidden",
        horizontal: "hidden",
      },
      minimap: {
        enabled: false,
      },
      readOnly: true,
    }}
    value={content}
    path={filePath}
    defaultValue="Please select a file"
    onMount={handleEditorDidMount}
    // onChange={(value) => onChange(value)}
  />
  {portalNodes && feedbacks && feedbacks.map((feedback, index) => {
    return portalNodes[index] && <portals.InPortal node={portalNodes[index]} key={feedback.id}><MyComponent /></portals.InPortal>;
  })}
</div>;
}