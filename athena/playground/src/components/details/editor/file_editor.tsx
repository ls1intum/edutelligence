import type { Feedback, FeedbackReferenceType } from "@/model/feedback";

import { useEffect, useRef, useState } from "react";
import { Editor, Monaco, useMonaco } from "@monaco-editor/react";
import { Position, Selection, editor } from "monaco-editor";

import {
  getFeedbackRange,
  getFeedbackReferenceType,
  getOnFeedbackChange,
} from "@/model/feedback";
import InlineFeedback from "./inline_feedback";
import { EditorWidget } from "./editor_widget";

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

  const monaco = useMonaco();
  const editorRef = useRef<editor.IStandaloneCodeEditor>();
  const feedbackWidgetsResizeObservers = useRef<(ResizeObserver | null)[]>([]);
  const addFileFeedbackResizeObserver = useRef<ResizeObserver | null>(null);
  const [hoverPosition, setHoverPosition] = useState<Position | undefined>(undefined);
  const [selection, setSelection] = useState<Selection | undefined>(undefined);
  const [
    addFeedbackDecorationsCollection,
    setAddFeedbackDecorationsCollection,
  ] = useState<editor.IEditorDecorationsCollection | undefined>(undefined);
  const [isMounted, setIsMounted] = useState(false);

  // Using state for non-react handlers is not working so we use a ref
  // This is a workaround to bridge the gap between react and monaco
  const latestAddFeedbackState = useRef({
    isPressed: false,
    selection: selection,
    hoverPosition: hoverPosition,
    feedbacks: feedbacks,
    filePath: filePath,
  });

  // Called when the user presses the add feedback button
  const addFeedbackPressed = (referenceType: FeedbackReferenceType) => {
    const model = editorRef.current?.getModel();
    if (!createNewFeedback || !onFeedbacksChange || !model) return;

    // Get the current state (workaround for non-react handlers)
    const { selection, hoverPosition, feedbacks, filePath } =
      latestAddFeedbackState.current;

    let newFeedback = createNewFeedback();
    if (referenceType === "referenced") {
      if (newFeedback.type === "text") {
        if (selection && !selection.isEmpty()) {
          const startIndex = model.getOffsetAt({
            lineNumber: selection.startLineNumber,
            column: selection.startColumn,
          });
          const endIndex = model.getOffsetAt({
            lineNumber: selection.endLineNumber,
            column: selection.endColumn,
          });
          newFeedback = {
            ...newFeedback,
            index_start: startIndex,
            index_end: endIndex,
          };
        } else if (hoverPosition) {
          const startIndex = model.getOffsetAt({
            lineNumber: hoverPosition.lineNumber,
            column: model.getLineMinColumn(hoverPosition.lineNumber),
          });
          const endIndex = model.getOffsetAt({
            lineNumber: hoverPosition.lineNumber,
            column: model.getLineMaxColumn(hoverPosition.lineNumber),
          });
          newFeedback = {
            ...newFeedback,
            index_start: startIndex,
            index_end: endIndex,
          };
        }
      } else if (newFeedback.type === "programming") {
        if (selection && !selection.isEmpty()) {
          newFeedback = {
            ...newFeedback,
            file_path: filePath,
            line_start: selection.startLineNumber,
            line_end:
              selection.startLineNumber !== selection.endLineNumber
                ? selection.endLineNumber
                : undefined,
          };
        } else if (hoverPosition) {
          newFeedback = {
            ...newFeedback,
            file_path: filePath,
            line_start: hoverPosition.lineNumber,
          };
        }
      }
    } else if (referenceType === "unreferenced_file") {
      if (newFeedback.type === "programming") {
        newFeedback = {
          ...newFeedback,
          file_path: filePath,
        };
      }
    }
    console.log(newFeedback);
    onFeedbacksChange([...(feedbacks ?? []), newFeedback]);
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
        latestAddFeedbackState.current.isPressed = true;
      }
    });

    editor.onMouseUp(function (e) {
      if (e.target.element?.className.includes("comment-range-button")) {
        if (latestAddFeedbackState.current.isPressed) {
          addFeedbackPressed("referenced");
        }
      }
      latestAddFeedbackState.current.isPressed = false;
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
    // setupFeedbackWidgets(editor);
    // setupAddFileFeedbackWidget(editor);
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
    console.log("Model updated");
  }, [monaco, filePath, content]);

  // Setup editor when it is mounted
  const handleEditorDidMount = (
    editor: editor.IStandaloneCodeEditor,
    monaco: Monaco
  ) => {
    console.log("Editor mounted");
    editorRef.current = editor;
    setIsMounted(true);
    setupEditor();
  };

  // Update add feedback decorations when the hover position or selection changes
  useEffect(() => {
    if (!editorRef.current || !monaco) return;
    setupAddFeedbackDecorations(editorRef.current, monaco);
    latestAddFeedbackState.current = {
      ...latestAddFeedbackState.current,
      selection,
      hoverPosition,
    };
  }, [hoverPosition, selection]);

  // Setup editor when something changes
  useEffect(() => {
    setupEditor();
    latestAddFeedbackState.current = {
      ...latestAddFeedbackState.current,
      feedbacks,
      filePath,
    };
  }, [feedbacks, content, filePath, monaco, editorRef]);

  // Cleanup observers on unmount
  useEffect(() => {
    return () => {
      feedbackWidgetsResizeObservers.current.forEach((observer) =>
        observer?.disconnect()
      );
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
      {editorRef.current && isMounted && (
        <>
          {onFeedbacksChange && filePath && (
            <EditorWidget
              editor={editorRef.current}
              afterLineNumber={0}
              afterColumn={1000}
              filePath={filePath}
            >
              <button
                className="mx-2 my-1 border-2 border-primary-400 border-dashed text-primary-500 hover:text-primary-600 hover:bg-primary-50 hover:border-primary-500 rounded-lg font-medium max-w-3xl w-full py-2"
                onClick={() => {
                  addFeedbackPressed("unreferenced_file");
                }}
              >
                Add file feedback
              </button>
            </EditorWidget>
          )}
          { feedbacks &&
            feedbacksToRender &&
            feedbacksToRender.map((feedback, index) => {
              const model = editorRef.current?.getModel();
              if (!editorRef.current || !model) return null;
              const range = getFeedbackRange(model, feedback);
              return (
                editorRef.current && (
                  <EditorWidget
                    editor={editorRef.current}
                    key={index}
                    afterLineNumber={range?.endLineNumber ?? 0}
                    afterColumn={range?.endColumn ?? 0}
                    filePath={filePath}
                  >
                    <InlineFeedback
                      feedback={feedback}
                      onFeedbackChange={
                        onFeedbacksChange &&
                        getOnFeedbackChange(feedbacks, index, onFeedbacksChange)
                      }
                      className="mr-4"
                    />
                  </EditorWidget>
                )
              );
            })}
        </>
      )}
    </div>
  );
}
