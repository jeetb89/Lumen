import { useState, useEffect, useCallback } from "react";
import { Box, AppBar, Toolbar, Typography } from "@mui/material";
import SmartToyOutlinedIcon from "@mui/icons-material/SmartToyOutlined";
import Sidebar from "./Sidebar";
import ChatPane from "./Chat";

export default function App() {
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [activeStream, setActiveStream] = useState(null); // AbortController | null
  const [modelKey, setModelKey] = useState("openai/gpt-4o-mini");

  const fetchConversations = useCallback(async () => {
    const res = await fetch("/api/conversations");
    if (res.ok) setConversations(await res.json());
  }, []);

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  useEffect(() => {
    if (!activeId) return;
    setMessages([]);
    fetch(`/api/conversations/${activeId}/messages`)
      .then((r) => r.json())
      .then(setMessages);
  }, [activeId]);

  async function newConversation() {
    const [provider, model] = modelKey.split("/");
    const res = await fetch("/api/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, model }),
    });
    const conv = await res.json();
    setConversations((prev) => [
      { id: conv.id, title: null, updated_at: new Date().toISOString(), last_message: null },
      ...prev,
    ]);
    setActiveId(conv.id);
    setMessages([]);
    setInput("");
  }

  async function sendMessage() {
    const text = input.trim();
    if (!text || activeStream || !activeId) return;

    setInput("");

    // Optimistic update — user message + empty streaming assistant placeholder
    setMessages((prev) => [
      ...prev,
      { id: `tmp-user-${Date.now()}`, role: "user", content: text },
      { id: `tmp-asst-${Date.now()}`, role: "assistant", content: "", streaming: true },
    ]);

    const controller = new AbortController();
    setActiveStream(controller);

    try {
      const res = await fetch(`/api/conversations/${activeId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: text }),
        signal: controller.signal,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        setMessages((prev) => {
          const copy = [...prev];
          copy[copy.length - 1] = {
            id: `err-${Date.now()}`,
            role: "error",
            content: `Error ${res.status}: ${err.detail ?? "unknown error"}`,
          };
          return copy;
        });
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true }); // stream:true handles multi-byte chars

        // SSE frames are separated by \n\n; keep the tail in case a frame is split
        const frames = buffer.split("\n\n");
        buffer = frames.pop();

        for (const frame of frames) {
          const lines = frame.split("\n");
          const eventLine = lines.find((l) => l.startsWith("event: "));
          const dataLine = lines.find((l) => l.startsWith("data: "));
          if (!eventLine || !dataLine) continue;

          const event = eventLine.slice(7);
          const data = JSON.parse(dataLine.slice(6));

          if (event === "delta") {
            setMessages((prev) => {
              const copy = [...prev];
              copy[copy.length - 1] = {
                ...copy[copy.length - 1],
                content: copy[copy.length - 1].content + data.text,
              };
              return copy;
            });
          } else if (event === "done") {
            setMessages((prev) => {
              const copy = [...prev];
              copy[copy.length - 1] = { ...copy[copy.length - 1], streaming: false };
              return copy;
            });
          }
        }
      }
    } catch (err) {
      if (err.name === "AbortError") {
        // Mark the placeholder as no longer streaming (partial text stays)
        setMessages((prev) => {
          const copy = [...prev];
          if (copy.length && copy[copy.length - 1].streaming) {
            copy[copy.length - 1] = { ...copy[copy.length - 1], streaming: false };
          }
          return copy;
        });
      } else {
        setMessages((prev) => {
          const copy = [...prev];
          copy[copy.length - 1] = {
            id: `err-${Date.now()}`,
            role: "error",
            content: `Error: ${err.message}`,
          };
          return copy;
        });
      }
    } finally {
      setActiveStream(null);
      fetchConversations(); // refresh sidebar titles + timestamps
    }
  }

  function cancelStream() {
    activeStream?.abort();
  }

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100dvh", bgcolor: "#0f0f0f" }}>
      <AppBar
        position="static"
        elevation={0}
        sx={{ bgcolor: "#111", borderBottom: "1px solid #222" }}
      >
        <Toolbar variant="dense" sx={{ gap: 1 }}>
          <SmartToyOutlinedIcon sx={{ color: "primary.main" }} />
          <Typography variant="h6" sx={{ fontWeight: 600, letterSpacing: 0.5 }}>
            OlliveBird
          </Typography>
        </Toolbar>
      </AppBar>

      <Box sx={{ flex: 1, display: "flex", overflow: "hidden" }}>
        <Sidebar
          conversations={conversations}
          activeId={activeId}
          onSelect={setActiveId}
          onNew={newConversation}
          modelKey={modelKey}
          onModelChange={setModelKey}
        />
        <ChatPane
          messages={messages}
          streaming={!!activeStream}
          input={input}
          onInputChange={setInput}
          onSend={sendMessage}
          onCancel={cancelStream}
          activeId={activeId}
        />
      </Box>
    </Box>
  );
}
