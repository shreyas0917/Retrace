import ReactMarkdown from "react-markdown";

/** Renders model-generated answer Markdown as React elements (no raw HTML). */
export function MarkdownAnswer({ text }: { text: string }) {
  // Strip literal bold markers; models often copy them from retrieved context.
  const normalized = text.replaceAll("**", "");
  const content = normalized.trim() ? normalized : "(no answer)";
  return (
    <div className="answer answer-md">
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  );
}
