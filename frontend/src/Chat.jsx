import { useRef, useEffect } from "react";
import {
  Box,
  TextField,
  IconButton,
  Typography,
  Paper,
  Divider,
  Button,
} from "@mui/material";
import SendIcon from "@mui/icons-material/Send";
import StopIcon from "@mui/icons-material/Stop";
import SmartToyOutlinedIcon from "@mui/icons-material/SmartToyOutlined";
import PersonOutlinedIcon from "@mui/icons-material/PersonOutlined";

function Message({ role, content, streaming }) {
  const isUser = role === "user";
  return (
    <Box
      sx={{
        display: "flex",
        justifyContent: isUser ? "flex-end" : "flex-start",
        gap: 1,
        alignItems: "flex-start",
      }}
    >
      {!isUser && (
        <SmartToyOutlinedIcon sx={{ mt: 0.5, color: "primary.main", fontSize: 20 }} />
      )}
      <Paper
        elevation={0}
        sx={{
          px: 2,
          py: 1.25,
          maxWidth: "75%",
          borderRadius: isUser ? "18px 18px 4px 18px" : "18px 18px 18px 4px",
          bgcolor: isUser ? "primary.main" : "background.paper",
          color: isUser ? "primary.contrastText" : "text.primary",
          border: isUser ? "none" : "1px solid",
          borderColor: "divider",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          fontSize: "0.95rem",
          lineHeight: 1.6,
        }}
      >
        {content || (streaming ? "" : "​")}
        {streaming && (
          <Box
            component="span"
            sx={{
              display: "inline-block",
              width: "2px",
              height: "1em",
              bgcolor: "text.primary",
              ml: "1px",
              verticalAlign: "text-bottom",
              animation: "blink 1s step-end infinite",
              "@keyframes blink": {
                "0%, 100%": { opacity: 1 },
                "50%": { opacity: 0 },
              },
            }}
          />
        )}
      </Paper>
      {isUser && (
        <PersonOutlinedIcon sx={{ mt: 0.5, color: "text.secondary", fontSize: 20 }} />
      )}
    </Box>
  );
}

export default function ChatPane({
  messages,
  streaming,
  input,
  onInputChange,
  onSend,
  onCancel,
  activeId,
}) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (streaming) onCancel();
      else onSend();
    }
  }

  return (
    <Box sx={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <Box
        sx={{
          flex: 1,
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: 2,
          py: 3,
          px: 3,
          maxWidth: 720,
          width: "100%",
          mx: "auto",
          alignSelf: "stretch",
        }}
      >
        {messages.length === 0 && !streaming && (
          <Box sx={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <Typography variant="body2" color="text.disabled">
              {activeId ? "No messages yet." : "Select or start a conversation."}
            </Typography>
          </Box>
        )}

        {messages.map((msg, i) =>
          msg.role === "error" ? (
            <Paper
              key={i}
              elevation={0}
              sx={{
                alignSelf: "center",
                px: 2,
                py: 1,
                bgcolor: "#3b0000",
                border: "1px solid #7f0000",
                color: "#fca5a5",
                borderRadius: 2,
                fontSize: "0.85rem",
              }}
            >
              {msg.content}
            </Paper>
          ) : (
            <Message
              key={msg.id ?? i}
              role={msg.role}
              content={msg.content}
              streaming={msg.streaming}
            />
          )
        )}

        <div ref={bottomRef} />
      </Box>

      <Divider sx={{ borderColor: "#222" }} />

      <Box
        sx={{
          py: 2,
          px: 3,
          display: "flex",
          gap: 1,
          alignItems: "flex-end",
          maxWidth: 720,
          width: "100%",
          mx: "auto",
        }}
      >
        <TextField
          fullWidth
          multiline
          maxRows={5}
          placeholder={activeId ? "Type a message…" : "Select or start a conversation first"}
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={!activeId}
          variant="outlined"
          size="small"
          autoFocus
          sx={{
            "& .MuiOutlinedInput-root": {
              bgcolor: "#1a1a1a",
              borderRadius: 3,
              "& fieldset": { borderColor: "#333" },
              "&:hover fieldset": { borderColor: "#555" },
              "&.Mui-focused fieldset": { borderColor: "primary.main" },
            },
            "& .MuiInputBase-input": { color: "#e8e8e8", fontSize: "0.95rem" },
            "& .MuiInputBase-input::placeholder": { color: "#555" },
          }}
        />

        {streaming ? (
          <Button
            onClick={onCancel}
            variant="outlined"
            size="small"
            startIcon={<StopIcon fontSize="small" />}
            sx={{
              borderColor: "#555",
              color: "#ccc",
              borderRadius: 2,
              px: 1.5,
              whiteSpace: "nowrap",
              alignSelf: "flex-end",
              mb: "2px",
              "&:hover": { borderColor: "#999", bgcolor: "#1a1a1a" },
            }}
          >
            Stop
          </Button>
        ) : (
          <IconButton
            onClick={onSend}
            disabled={!activeId || !input.trim()}
            sx={{
              bgcolor: "primary.main",
              color: "#fff",
              borderRadius: 2,
              p: 1,
              "&:hover": { bgcolor: "primary.dark" },
              "&.Mui-disabled": { bgcolor: "#1e3a6e", color: "#555" },
            }}
          >
            <SendIcon fontSize="small" />
          </IconButton>
        )}
      </Box>
    </Box>
  );
}
