import type { ModelingExercise } from "@/model/exercise";

import Disclosure from "@/components/disclosure";
import React, { useRef, useEffect, useState, use } from "react";

export default function ModelingExerciseDetail({
  exercise,
  openedInitially,
}: {
  exercise: ModelingExercise;
  openedInitially?: boolean;
}) {

  const editorRef = useRef<HTMLDivElement>(null);

  const [editor, setEditor] = useState<any>(undefined);

  useEffect(() => {
    return () => {
      editor?.destroy();
    }
  }, [editor]);

  useEffect(() => {
     if (!editorRef?.current) {
      return;
    }
    
    // Dynamically import both ApollonEditor and importDiagram to avoid SSR issues
    import('@tumaet/apollon').then(({ ApollonEditor, importDiagram }) => {
      setEditor(new ApollonEditor(editorRef.current!, {
        model: importDiagram(JSON.parse(exercise.example_solution || '{}')),
        readonly: true,
        scale: 0.8
      }));
    });

  }, [editorRef, exercise]);

  return (
    <>
    {/* Forced mount to ensure the editor is initialized even if the content is not visible initially -> Workaround for nested Disclosures */}
    <Disclosure title="Example Solution" noContentIndent openedInitially={openedInitially} forceMount>
      {(exercise.example_solution?.length ?? 0) > 0 ? (
        <div className="border border-gray-100 rounded-lg overflow-hidden">
          <div ref={editorRef} style={{ height: 400 }}/>
        </div>
      ) : (
        <span className="text-gray-500">No example solution available</span>
      )}
    </Disclosure>
    </>
  );
}
