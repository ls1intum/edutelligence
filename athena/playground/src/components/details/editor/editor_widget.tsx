import { editor } from "monaco-editor";
import { createHtmlPortalNode, InPortal, OutPortal } from "react-reverse-portal";
import { createRoot } from "react-dom/client";
import { useEffect, useId, useMemo, useRef, useState } from "react";

type EditorWidgetProps = {
  editor: editor.IStandaloneCodeEditor;
  children: React.ReactNode;
  afterLineNumber: number;
  afterColumn?: number;
};

export function EditorWidget({ editor, children, afterLineNumber, afterColumn }: EditorWidgetProps) {
  const id = useId();
  const portalNode = useMemo(() => createHtmlPortalNode(), []);
  const resizeObserverRef = useRef<ResizeObserver>();
  const overlayWidgetRef = useRef<editor.IOverlayWidget>();
  const zoneIdRef = useRef<string>();
  
  const updateWidget = () => {
    console.log(`Create view zone for ${id}`)
    const overlayNode = document.createElement("div");
    overlayNode.id = `widget-${id}-overlay`;
    overlayNode.style.width = "100%";
    const root = createRoot(overlayNode);
    root.render(<OutPortal node={portalNode} />);

    const overlayWidget: editor.IOverlayWidget = {
      getId: () => `widget-${id}-overlay-widget`,
      getDomNode: () => overlayNode,
      getPosition: () => null,
    };
    editor.addOverlayWidget(overlayWidget)
    overlayWidgetRef.current = overlayWidget;

    const zoneNode = document.createElement("div");
    zoneNode.id = `widget-${id}-zone`;

    editor.changeViewZones(function (changeAccessor) {
      console.log(`Change view zone for ${id}`)
      const overlayNode = overlayWidget.getDomNode();
      const zoneId = changeAccessor.addZone({
        afterLineNumber,
        afterColumn,
        domNode: zoneNode,
        get heightInPx() {
          return overlayNode.offsetHeight;
        },
        onDomNodeTop: (top) => {
          overlayNode.style.top = top + "px";
        },
      });
      zoneIdRef.current = zoneId;

      const observer = new ResizeObserver(() => {
        editor.changeViewZones((accessor) => accessor.layoutZone(zoneId));
      });
      observer.observe(overlayNode);
      resizeObserverRef.current?.disconnect();
      resizeObserverRef.current = observer;
    });
  };
 
  useEffect(() => {
    console.log(`Mount ${id}`)
    updateWidget();
    const didChangeModelListener = editor.onDidChangeModelContent(() => {
      console.log(`Model changed for ${id}`)
      updateWidget();
    });
    const didResizeListener = editor.onDidContentSizeChange(() => {
      console.log(`Content size changed for ${id}`)
      editor.changeViewZones((accessor) => accessor.layoutZone(zoneIdRef.current!));
    });

    return () => {
      console.log(`Unmount ${id}`);
      didChangeModelListener.dispose();
      resizeObserverRef.current?.disconnect();
      editor.changeViewZones((accessor) => {
        console.log(`Remove view zone for ${id}`)
        accessor.removeZone(zoneIdRef.current!);
      }
      );
      editor.removeOverlayWidget(overlayWidgetRef.current!);
    };
  }, []);

  return (
    <InPortal node={portalNode}>{children}</InPortal>
  );
}
