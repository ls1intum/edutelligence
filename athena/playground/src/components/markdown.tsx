import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { twMerge } from "tailwind-merge";
import rehypeRaw from 'rehype-raw'

type MarkdownProps = {
  content: string;
  enablePlainTextSwitcher?: boolean;
  className?: string;
};

export default function Markdown({
  content,
  enablePlainTextSwitcher,
  className,
}: MarkdownProps) {
  const [view, setView] = useState<"markdown" | "plaintext">("markdown");

  const switcherButton = enablePlainTextSwitcher && (
    <div className="inline-flex rounded-md shadow-sm mb-2" role="group">
      <button
        type="button"
        className={twMerge(
          "inline-flex items-center px-4 py-1 text-sm font-medium text-slate-900 bg-white border border-slate-200 rounded-l-lg hover:bg-slate-100",
          view === "markdown"
            ? "bg-slate-700 text-white hover:bg-slate-800"
            : ""
        )}
        onClick={() => setView("markdown")}
      >
        Markdown
      </button>
      <button
        type="button"
        className={twMerge(
          "inline-flex items-center px-4 py-1 text-sm font-medium text-slate-900 bg-white border border-slate-200 rounded-r-lg hover:bg-slate-100",
          view === "plaintext"
            ? "bg-slate-700 text-white hover:bg-slate-800"
            : ""
        )}
        onClick={() => setView("plaintext")}
      >
        Plain Text
      </button>
    </div>
  );

  const plainTextView = (
    <pre
      className={twMerge("text-sm max-w-none whitespace-pre-wrap ", className)}
    >
      {content}
    </pre>
  );

  const markdownView = (
      (<div className={twMerge("prose prose-sm max-w-none", className)}>
          <ReactMarkdown rehypePlugins={[rehypeRaw]}>
              {content}
          </ReactMarkdown>
      </div>)
  );

  return (
    <div>
      {switcherButton}
      <div className="bg-slate-100 p-4 rounded-md">
        {view === "plaintext" ? plainTextView : markdownView}
      </div>
    </div>
  );
}
