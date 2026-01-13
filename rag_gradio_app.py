# rag_gradio_app.py
#
# Gradio UI to interact with your RAG LLM.
# - Uses messages-style history: [{"role": "user", "content": ...}, ...]
# - No use of type="messages" (your Gradio version doesn't support it).

from typing import List, Dict
import gradio as gr

from query_rag import answer_query_with_context


def format_contexts(contexts: List[Dict]) -> str:
    """
    Nicely format the retrieved chunks for display under the answer.
    """
    if not contexts:
        return "No context chunks were retrieved."

    lines = []
    for i, ctx in enumerate(contexts, start=1):
        m = ctx.get("metadata", {}) or {}
        paper_id = m.get("paper_id", "unknown")
        title = (m.get("title") or "").strip()
        section = m.get("section")
        section_str = f" – section: {section}" if section else ""

        header = f"[S{i}] {paper_id} – {title}{section_str}"
        chunk_text = ctx.get("text", "") or ""

        # Truncate chunk text so UI does not explode
        if len(chunk_text) > 800:
            chunk_text = chunk_text[:800] + "..."

        lines.append(f"**{header}**\n\n{chunk_text}\n")

    return "\n---\n\n".join(lines)


def rag_chat(
    message: str,
    history: List[Dict],
    persist_dir: str,
    collection_name: str,
    k: int,
    show_context: bool,
):
    """
    Chat handler for Gradio.

    history is a list like:
      [
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "..."},
        ...
      ]
    """
    if history is None:
        history = []

    # Call your RAG function
    answer, contexts = answer_query_with_context(
        query=message,
        persist_dir=persist_dir,
        collection_name=collection_name,
        k=k,
    )

    if show_context:
        ctx_text = format_contexts(contexts)
        answer_to_show = (
            answer
            + "\n\n---\n\n"
            + "### Retrieved context chunks\n\n"
            + ctx_text
        )
    else:
        answer_to_show = answer

    # Append user & assistant messages in messages format
    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": answer_to_show},
    ]

    # Return: cleared textbox, updated history
    return "", history


with gr.Blocks() as demo:
    gr.Markdown(
        """
        # RAG Chat Interface

        Ask questions and get answers from your local LLM, grounded in your Chroma RAG index.
        """
    )

    with gr.Row():
        with gr.Column(scale=3):
            # Chatbot now expects a list of {role, content} dicts
            chatbot = gr.Chatbot(
                label="RAG Chat",
            )
            msg = gr.Textbox(
                label="Your question",
                placeholder="Ask something about your indexed documents...",
            )
            clear = gr.Button("Clear conversation")

        with gr.Column(scale=1):
            gr.Markdown("### RAG settings")
            persist_dir_input = gr.Textbox(
                label="Chroma persist directory",
                value="./rag_db",
            )
            collection_name_input = gr.Textbox(
                label="Collection name",
                value="papers",
            )
            k_slider = gr.Slider(
                label="Number of chunks (k)",
                minimum=1,
                maximum=20,
                step=1,
                value=5,
            )
            show_context_checkbox = gr.Checkbox(
                label="Show retrieved context chunks under the answer",
                value=True,
            )

    # Submit: textbox -> rag_chat
    msg.submit(
        fn=rag_chat,
        inputs=[
            msg,
            chatbot,               # current history (messages format)
            persist_dir_input,
            collection_name_input,
            k_slider,
            show_context_checkbox,
        ],
        outputs=[msg, chatbot],    # clear msg, update chatbot
    )

    # Clear conversation
    clear.click(
        fn=lambda: ("", []),       # empty textbox, empty history (list of messages)
        inputs=None,
        outputs=[msg, chatbot],
    )

if __name__ == "__main__":
    demo.launch()
