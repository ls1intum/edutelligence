import { Feedback } from "@/model/feedback";
import { useEffect, useMemo, useRef, useState } from "react";
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

  const portalNode = useMemo(() => portals.createHtmlPortalNode(), []);
  const resizeObserver = useRef<ResizeObserver | null>(null);

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
    
    const overlayDom = document.createElement("div");
    overlayDom.id = 'overlayId';
    overlayDom.style.width = '100%';
    // overlayDom.style.background = '#0000ff';
    const root = createRoot(overlayDom);
    root.render(<portals.OutPortal node={portalNode} />);
    
    var overlayWidget = {
      getId: () => "my.overlay.widget",
      getDomNode: () => overlayDom,
      getPosition: () => null,
    };
    editor.addOverlayWidget(overlayWidget);

    let zoneNode = document.createElement('div');
    zoneNode.id = "zoneId";

    editorRef.current?.changeViewZones(function (changeAccessor) {
      
      const zoneId = changeAccessor.addZone({
        afterLineNumber: 3,
        domNode: zoneNode,
        get heightInPx() {
          return overlayDom.offsetHeight;
        },
        onDomNodeTop: top => {
          overlayDom.style.top = top + "px";
        },
      });
      resizeObserver.current = new ResizeObserver(() => {
        editor.changeViewZones(accessor => accessor.layoutZone(zoneId));
      });
      resizeObserver.current.observe(overlayDom);
    });
  }

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      resizeObserver.current?.disconnect();
      resizeObserver.current = null;
    };
  }, []);

  return <div className="h-[50vh]">
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
  <portals.InPortal node={portalNode}><MyComponent /></portals.InPortal>
</div>;
}