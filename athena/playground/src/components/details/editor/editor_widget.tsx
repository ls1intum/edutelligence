import { editor } from "monaco-editor";
import { createHtmlPortalNode, InPortal, OutPortal } from "react-reverse-portal";
import { createRoot } from "react-dom/client";
import { useEffect, useId, useMemo, useRef, useState } from "react";

type EditorWidgetProps = {
  editor: editor.IStandaloneCodeEditor;
  children: React.ReactNode;
  afterLineNumber: number;
  afterColumn?: number;
  filePath?: string;
};

export function EditorWidget({ editor, children, afterLineNumber, afterColumn, filePath }: EditorWidgetProps) {
  const id = useId();
  const portalNode = useMemo(() => createHtmlPortalNode(), []);
  const resizeObserverRef = useRef<ResizeObserver>();
  const overlayWidgetRef = useRef<editor.IOverlayWidget>();
  const zoneIdRef = useRef<string>();
  
  const updateWidget = () => {
    overlayWidgetRef.current && editor.removeOverlayWidget(overlayWidgetRef.current);
    zoneIdRef.current && editor.changeViewZones((accessor) => accessor.removeZone(zoneIdRef.current!));

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
    updateWidget();

    // Last resort workaround for the widget not being created
    const observer = new MutationObserver((mutationsList, observer) => {
      // If the widget doesn't exist, update it
      if (!document.getElementById(`widget-${id}-zone`)) {
        updateWidget();
      }
    });
    
    // Start observing the document with the configured parameters
    observer.observe(document, { childList: true, subtree: true });

    return () => {
      resizeObserverRef.current?.disconnect();
      observer.disconnect();
      editor.removeOverlayWidget(overlayWidgetRef.current!);
      editor.changeViewZones((accessor) => accessor.removeZone(zoneIdRef.current!));
    };
  }, [filePath]);

  return (
    <InPortal node={portalNode}>{children}</InPortal>
  );
}
