import type { Feedback, FeedbackReferenceType } from "@/model/feedback";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Editor, Monaco, useMonaco } from "@monaco-editor/react";
import { Position, Selection, editor } from "monaco-editor";
import * as portals from "react-reverse-portal";
import { createRoot } from "react-dom/client";

import { getFeedbackRange, getFeedbackReferenceType } from "@/model/feedback";
import InlineFeedback from "./inline_feedback";

type FileEditorProps = {
  content: string;
  filePath?: string;
  feedbacks?: Feedback[];
  onFeedbacksChange?: (feedback: Feedback[]) => void;
  createNewFeedback?: () => Feedback;
};

export default function FileEditor({
  content,
  filePath,
  feedbacks,
  onFeedbacksChange,
  createNewFeedback,
}: FileEditorProps) {
  // Only render feedbacks that are relevant to the current file
  // Unreferenced feedbacks are always shown
  const feedbacksToRender = feedbacks?.filter((feedback) => {
    const referenceType = getFeedbackReferenceType(feedback);
    if (referenceType === "unreferenced") {
      return false;
    }
    if ("file_path" in feedback) {
      return feedback.file_path === filePath;
    } else {
      return true;
    }
  });

  const id = useId();
  const monaco = useMonaco();
  const editorRef = useRef<editor.IStandaloneCodeEditor>();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const feedbackWidgetsPortalNodes = useMemo(
    () => feedbacksToRender?.map(() => portals.createHtmlPortalNode()),
    [feedbacks, content, filePath]
  );
  const addFileFeedbackPortalNode = useRef(portals.createHtmlPortalNode());
  const feedbackWidgetsResizeObservers = useRef<(ResizeObserver | null)[]>([]);
  const addFileFeedbackResizeObserver = useRef<ResizeObserver | null>(null);
  const [hoverPosition, setHoverPosition] = useState<Position | undefined>(undefined);
  const [selection, setSelection] = useState<Selection | undefined>(undefined);
  const [
    feedbackWidgetDecorationsCollection,
    setFeedbackWidgetDecorationsCollection,
  ] = useState<editor.IEditorDecorationsCollection | undefined>(undefined);
  const [
    addFeedbackDecorationsCollection,
    setAddFeedbackDecorationsCollection,
  ] = useState<editor.IEditorDecorationsCollection | undefined>(undefined);
  // useState is not used here because we don't want to re-render when the value changes
  const isAddFeedbackPressed = useRef(false);

  // Called when the user presses the add feedback button
  const addFeedbackPressed = (referenceType: FeedbackReferenceType) => {
    console.log("Add feedback", referenceType);
    // TODO create empty feedback
  };

  // Setup feedback widgets for each feedback
  const setupFeedbackWidgets = (editor: editor.IStandaloneCodeEditor) => {
    const feedbackRanges = feedbacksToRender?.map((feedback) =>
      getFeedbackRange(content, feedback)
    );

    // Add feedback overlay widgets for each feedback
    let overlayNodes: HTMLDivElement[] = [];
    feedbacksToRender?.forEach((_, index) => {
      const portalNode = feedbackWidgetsPortalNodes![index]!;

      const overlayNode = document.createElement("div");
      overlayNode.id = `feedback-${id}-${index}-overlay`;
      overlayNode.style.width = "100%";
      const root = createRoot(overlayNode);
      root.render(<portals.OutPortal node={portalNode} />);

      var overlayWidget = {
        getId: () => `feedback-${id}-${index}-widget`,
        getDomNode: () => overlayNode,
        getPosition: () => null,
      };
      editor.addOverlayWidget(overlayWidget);
      overlayNodes.push(overlayNode);
    });

    // Add view zones for each feedback to push the content down
    editor.changeViewZones(function (changeAccessor) {
      feedbacksToRender?.forEach((feedback, index) => {
        const overlayNode = overlayNodes[index];
        const zoneNode = document.createElement("div");
        zoneNode.id = `feedback-${id}-${index}-zone`;

        const referenceType = getFeedbackReferenceType(feedback);
        // Unreferenced and unreferenced_file feedbacks are always shown at the top
        const afterLineNumber = feedbackRanges![index]?.startLineNumber ?? 0;
        // Order unreferenced feedback before unreferenced_file feedback
        const afterColumn =
          referenceType === "unreferenced"
            ? 0
            : referenceType === "unreferenced_file"
            ? 1
            : feedbackRanges![index]?.startColumn;

        const zoneId = changeAccessor.addZone({
          afterLineNumber: afterLineNumber,
          afterColumn: afterColumn,
          domNode: zoneNode,
          get heightInPx() {
            return overlayNode.offsetHeight;
          },
          onDomNodeTop: (top) => {
            overlayNode.style.top = top + "px";
          },
        });
        const observer = new ResizeObserver(() => {
          editor.changeViewZones((accessor) => accessor.layoutZone(zoneId));
        });
        observer.observe(overlayNode);
        feedbackWidgetsResizeObservers.current.push(observer);
      });
    });

    // Add line decorations for each feedback to highlight the text
    if (feedbackWidgetDecorationsCollection) {
      feedbackWidgetDecorationsCollection.clear();
    }
    const newDecorationsCollection = editor.createDecorationsCollection(
      feedbackRanges?.flatMap((range, index) =>
        range
          ? [
              {
                options: {
                  inlineClassName: `inline-feedback-text ${
                    feedbacksToRender![index].credits < 0
                      ? "negative"
                      : feedbacksToRender![index].credits > 0
                      ? "positive"
                      : "neutral"
                  }`,
                },
                range,
              },
            ]
          : []
      ) ?? []
    );
    setFeedbackWidgetDecorationsCollection(newDecorationsCollection);
  };

  // Setup add file feedback button
  const setupAddFileFeedbackWidget = (editor: editor.IStandaloneCodeEditor) => {
    if (!onFeedbacksChange && filePath) return;

    // Add file feedback button overlay widget
    const overlayNode = document.createElement("div");
    overlayNode.id = `feedback-${id}-add-file-feedback-overlay`;
    overlayNode.style.width = "100%";
    const root = createRoot(overlayNode);
    root.render(<portals.OutPortal node={addFileFeedbackPortalNode.current} />);

    var overlayWidget = {
      getId: () => `feedback-${id}-add-file-feedback-widget`,
      getDomNode: () => overlayNode,
      getPosition: () => null,
    };
    editor.addOverlayWidget(overlayWidget);

    // Add view zone for the file feedback button to push the content down
    editor.changeViewZones(function (changeAccessor) {
      const zoneNode = document.createElement("div");
      zoneNode.id = `feedback-${id}-add-file-feedback-zone`;
      const zoneId = changeAccessor.addZone({
        afterLineNumber: 0,
        afterColumn: 1000, // To make sure it is always at the bottom
        domNode: zoneNode,
        get heightInPx() {
          return overlayNode.offsetHeight;
        },
        onDomNodeTop: (top) => {
          overlayNode.style.top = top + "px";
        },
      });
      const observer = new ResizeObserver(() => {
        editor.changeViewZones((accessor) => accessor.layoutZone(zoneId));
      });
      observer.observe(overlayNode);
      addFileFeedbackResizeObserver.current = observer;
    });
  };

  // Setup listeners for adding feedback
  // Listening for mouse and selection events for adding feedback
  const setupAddFeedbackListeners = (editor: editor.IStandaloneCodeEditor) => {
    editor.onMouseMove(function (e) {
      setHoverPosition(e.target.position ?? undefined);
    });

    editor.onDidChangeCursorSelection(function (e) {
      setSelection(e.selection);
    });

    editor.onMouseDown(function (e) {
      if (e.target.element?.className.includes("comment-range-button")) {
        isAddFeedbackPressed.current = true;
      }
    });

    editor.onMouseUp(function (e) {
      if (e.target.element?.className.includes("comment-range-button")) {
        if (isAddFeedbackPressed.current) {
          addFeedbackPressed("referenced");
        }
      }
      isAddFeedbackPressed.current = false;
    });
  };

  // Setup decorations for adding feedback (in the gutter)
  const setupAddFeedbackDecorations = (
    editor: editor.IStandaloneCodeEditor,
    monaco: Monaco
  ) => {
    if (addFeedbackDecorationsCollection) {
      addFeedbackDecorationsCollection.clear();
    }
    if (hoverPosition === undefined && selection === undefined) {
      setAddFeedbackDecorationsCollection(undefined);
      return;
    }

    if (selection && !selection.isEmpty()) {
      const decorations: editor.IModelDeltaDecoration[] = [
        {
          range: new monaco.Range(
            selection.startLineNumber,
            selection.startColumn,
            selection.endLineNumber,
            selection.endColumn
          ),
          options: {
            linesDecorationsClassName: "comment-range",
          },
        },
        {
          range: new monaco.Range(
            selection.endLineNumber,
            selection.endColumn,
            selection.endLineNumber,
            selection.endColumn
          ),
          options: {
            linesDecorationsClassName: "comment-range-button",
          },
        },
      ];
      const newAddFeedbackDecorationsCollection =
        editor.createDecorationsCollection(decorations);
      setAddFeedbackDecorationsCollection(newAddFeedbackDecorationsCollection);
    } else if (hoverPosition) {
      const decorations: editor.IModelDeltaDecoration[] = [
        {
          range: new monaco.Range(
            hoverPosition.lineNumber,
            1,
            hoverPosition.lineNumber,
            1
          ),
          options: {
            isWholeLine: true,
            linesDecorationsClassName: "comment-range",
          },
        },
        {
          range: new monaco.Range(
            hoverPosition.lineNumber,
            hoverPosition.column,
            hoverPosition.lineNumber,
            hoverPosition.column
          ),
          options: { linesDecorationsClassName: "comment-range-button" },
        },
      ];
      const newAddFeedbackDecorationsCollection =
        editor.createDecorationsCollection(decorations);
      setAddFeedbackDecorationsCollection(newAddFeedbackDecorationsCollection);
    } else {
      setAddFeedbackDecorationsCollection(undefined);
    }
  };

  const setupEditor = () => {
    if (!editorRef.current || !monaco) return;
    const editor = editorRef.current;
    setupFeedbackWidgets(editor);
    setupAddFileFeedbackWidget(editor);
    setupAddFeedbackListeners(editor);
    setupAddFeedbackDecorations(editor, monaco);
  };

  // Update the model when the content or filePath changes (for syntax highlighting)
  useEffect(() => {
    if (!monaco) return;
    const path = monaco.Uri.parse(filePath || "");
    monaco.editor.getModel(path)?.dispose();
    const model = monaco.editor.createModel(content, undefined, path);
    editorRef.current?.setModel(model);
  }, [monaco, filePath, content]);

  // Setup editor when it is mounted
  const handleEditorDidMount = (
    editor: editor.IStandaloneCodeEditor,
    monaco: Monaco
  ) => {
    editorRef.current = editor;
    setupEditor();
  };

  // Update add feedback decorations when the hover position or selection changes
  useEffect(() => {
    if (!editorRef.current || !monaco) return;
    setupAddFeedbackDecorations(editorRef.current, monaco);
  }, [hoverPosition, selection]);

  // Setup editor when something changes
  useEffect(() => {
    setupEditor();
  }, [feedbacks, content, filePath, monaco, editorRef]);

  // Cleanup observers on unmount
  useEffect(() => {
    return () => {
      feedbackWidgetsResizeObservers.current.forEach((observer) => observer?.disconnect());
      feedbackWidgetsResizeObservers.current = [];
      addFileFeedbackResizeObserver.current?.disconnect();
      addFileFeedbackResizeObserver.current = null;
    };
  }, []);

  return (
    <div className="h-[50vh]">
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
          lineDecorationsWidth: 20,
          folding: false,
          wordWrap: "on",
        }}
        value={content}
        path={filePath}
        defaultValue="Please select a file"
        onMount={handleEditorDidMount}
      />
      {onFeedbacksChange && filePath && (
        <portals.InPortal node={addFileFeedbackPortalNode.current}>
          <button
            className="mx-2 my-1 border-2 border-primary-400 border-dashed text-primary-500 hover:text-primary-600 hover:bg-primary-50 hover:border-primary-500 rounded-lg font-medium max-w-3xl w-full py-2"
            onClick={() => {
              addFeedbackPressed("unreferenced_file");
            }}
          >
            Add file feedback
          </button>
        </portals.InPortal>
      )}
      {feedbackWidgetsPortalNodes &&
        feedbacks &&
        feedbacksToRender &&
        feedbacksToRender.map((feedback, index) => {
          return (
            feedbackWidgetsPortalNodes[index] && (
              <portals.InPortal
                node={feedbackWidgetsPortalNodes[index]}
                key={feedback.id}
              >
                <div className="mr-4">
                  <InlineFeedback
                    feedback={feedback}
                    onFeedbackChange={
                      onFeedbacksChange &&
                      ((newFeedback) => {
                        if (newFeedback) {
                          onFeedbacksChange(
                            feedbacks.map((f) =>
                              f.id === feedback.id ? newFeedback : f
                            )
                          );
                        } else {
                          onFeedbacksChange(
                            feedbacks.filter((f) => f.id !== feedback.id)
                          );
                        }
                      })
                    }
                  />
                </div>
              </portals.InPortal>
            )
          );
        })}
    </div>
  );
}
