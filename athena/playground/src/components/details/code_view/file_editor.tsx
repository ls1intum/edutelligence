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

const MyComponent = ({ layoutViewZoneFunc }: { layoutViewZoneFunc?: () => void }) => {
  const [count, setCount] = useState<number>(0);

  useEffect(() => {
    if (layoutViewZoneFunc) {
      layoutViewZoneFunc();
    }
  }, [layoutViewZoneFunc])

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
  const [layoutViewZoneFunc, setLayoutViewZoneFunc] = useState<(() => void) | undefined>(undefined);

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
          console.log("offsetHeight", overlayDom.offsetHeight)
          console.log("clientHeight", overlayDom.clientHeight)
          console.log("scrollHeight", overlayDom.scrollHeight)
          console.log("styleHeight", overlayDom.style.height)
          return overlayDom.offsetHeight;
        },
        onDomNodeTop: top => {
          overlayDom.style.top = top + "px";
        },
        // onComputedHeight: height => {
        //   overlayDom.style.height = height + "px";
        // }
      });
      setLayoutViewZoneFunc(() => () => {
        console.log("layoutViewZoneFunc")
        editorRef.current?.changeViewZones(function (changeAccessor) {
          changeAccessor.layoutZone(zoneId);
        });
      });
    });
  }

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
  <portals.InPortal node={portalNode}><MyComponent layoutViewZoneFunc={layoutViewZoneFunc} /></portals.InPortal>
</div>;
}