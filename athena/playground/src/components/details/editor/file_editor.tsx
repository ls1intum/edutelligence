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
  identifier?: string;
  filePath?: string;
  noFileFeedback?: boolean;
  autoHeight?: boolean;
  feedbacks?: Feedback[];
  onFeedbacksChange?: (feedback: Feedback[]) => void;
  createNewFeedback?: () => Feedback;
};

export default function FileEditor({
  content,
  identifier,
  filePath,
  noFileFeedback = false,
  autoHeight = false,
  feedbacks,
  onFeedbacksChange,
  createNewFeedback,
}: FileEditorProps) {
  const monaco = useMonaco();
  const editorRef = useRef<editor.IStandaloneCodeEditor>();

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
  const modelPath = (identifier ? `${identifier}/` : "") + (filePath ?? "default");

  // Height used for autoHeight
  const [height, setHeight] = useState<number>(18);
  const [hoverPosition, setHoverPosition] = useState<Position | undefined>(undefined);
  const [selection, setSelection] = useState<Selection | undefined>(undefined);
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
  const addFeedbackHoverDecorations = useRef<string[]>([]);

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
          newFeedback.index_start = model.getOffsetAt({
            lineNumber: selection.startLineNumber,
            column: selection.startColumn,
          });
          newFeedback.index_end = model.getOffsetAt({
            lineNumber: selection.endLineNumber,
            column: selection.endColumn,
          });
        } else if (hoverPosition) {
          newFeedback.index_start = model.getOffsetAt({
            lineNumber: hoverPosition.lineNumber,
            column: model.getLineMinColumn(hoverPosition.lineNumber),
          });
          newFeedback.index_end = model.getOffsetAt({
            lineNumber: hoverPosition.lineNumber,
            column: model.getLineMaxColumn(hoverPosition.lineNumber),
          });
        }
      } else if (newFeedback.type === "programming") {
        if (selection && !selection.isEmpty()) {
          newFeedback.file_path = filePath;
          newFeedback.line_start = selection.startLineNumber;
          newFeedback.line_end =
            selection.startLineNumber !== selection.endLineNumber
              ? selection.endLineNumber
              : undefined;
        } else if (hoverPosition) {
          newFeedback.file_path = filePath;
          newFeedback.line_start = hoverPosition.lineNumber;
        }
      }
    } else if (referenceType === "unreferenced_file") {
      if (newFeedback.type === "programming") {
        newFeedback.file_path = filePath;
      }
    }
    onFeedbacksChange([...(feedbacks ?? []), newFeedback]);
  };

  // Setup listeners for adding feedback
  // Listening for mouse and selection events for adding feedback
  const setupAddFeedbackHoverListeners = (editor: editor.IStandaloneCodeEditor) => {
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

  // Update decorations for adding feedback (in the gutter)
  const updateAddFeedbackHoverDecorations = (
    editor: editor.IStandaloneCodeEditor,
    monaco: Monaco
  ) => {
    const model = editor.getModel();
    if (!model || model.isDisposed()) return;

    if (hoverPosition === undefined && selection === undefined) {
      model.deltaDecorations(addFeedbackHoverDecorations.current, []);
      return;
    }

    if (selection && !selection.isEmpty()) {
      addFeedbackHoverDecorations.current = model.deltaDecorations(
        addFeedbackHoverDecorations.current,
        [
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
        ]
      );
    } else if (hoverPosition) {
      addFeedbackHoverDecorations.current = model.deltaDecorations(
        addFeedbackHoverDecorations.current,
        [
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
        ]
      );
    } else {
      model.deltaDecorations(addFeedbackHoverDecorations.current, []);
    }
  };

  // Update the model when the content or filePath changes (for syntax highlighting)
  useEffect(() => {
    if (!monaco) return;

    monaco.editor.getModel(monaco.Uri.parse(modelPath))?.dispose();
    const model = monaco.editor.createModel(
      content,
      undefined,
      monaco.Uri.parse(modelPath)
    );
    editorRef.current?.setModel(model);
  }, [filePath]);

  // Setup editor when it is mounted
  const handleEditorDidMount = (
    editor: editor.IStandaloneCodeEditor,
    monaco: Monaco
  ) => {
    editorRef.current = editor;
    setIsMounted(true);
    if (onFeedbacksChange) {
      setupAddFeedbackHoverListeners(editor);
      updateAddFeedbackHoverDecorations(editorRef.current, monaco);
    }

    if (autoHeight) {
      editor.onDidContentSizeChange(() => {
        setHeight(Math.min(1000, editor.getContentHeight()));
        editor.layout();
      });
    }
  };

  // Update add feedback decorations when the hover position or selection changes
  useEffect(() => {
    if (!onFeedbacksChange || !editorRef.current || !monaco) return;
    updateAddFeedbackHoverDecorations(editorRef.current, monaco);
    latestAddFeedbackState.current = {
      ...latestAddFeedbackState.current,
      selection,
      hoverPosition,
    };
  }, [hoverPosition, selection]);

  useEffect(() => {
    latestAddFeedbackState.current = {
      ...latestAddFeedbackState.current,
      feedbacks,
      filePath,
    };
  }, [feedbacks, content, filePath, monaco, editorRef]);

  return (
    <>
      <div style={autoHeight ? { height } : {}} className="h-full">
        <Editor
          options={{
            automaticLayout: true,
            scrollBeyondLastLine: !autoHeight,
            scrollbar: {
              vertical: "hidden",
              horizontal: "hidden",
              alwaysConsumeMouseWheel: !autoHeight || height === 1000,
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
          path={modelPath}
          defaultValue="Please select a file"
          onMount={handleEditorDidMount}
        />
      </div>
      {editorRef.current && isMounted && (
        <>
          {onFeedbacksChange && !noFileFeedback && (
            <EditorWidget
              key={filePath}
              editor={editorRef.current}
              afterLineNumber={0}
              afterColumn={1000}
              modelPath={modelPath}
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
          {feedbacks &&
            feedbacksToRender &&
            feedbacksToRender.map((feedback, index) => {
              const model = editorRef.current?.getModel();
              if (!editorRef.current || !model) return null;
              const range = getFeedbackRange(model, feedback);
              return (
                editorRef.current && (
                  <EditorWidget
                    editor={editorRef.current}
                    key={`${filePath}-feedback-${feedback.id}-${index}`}
                    afterLineNumber={range?.endLineNumber ?? 0}
                    afterColumn={range?.endColumn ?? 0}
                    modelPath={modelPath}
                  >
                    <InlineFeedback
                      feedback={feedback}
                      onFeedbackChange={
                        onFeedbacksChange &&
                        getOnFeedbackChange(
                          feedback,
                          feedbacks,
                          onFeedbacksChange
                        )
                      }
                      model={model}
                      className="mr-4"
                    />
                  </EditorWidget>
                )
              );
            })}
        </>
      )}
    </>
  );
}
