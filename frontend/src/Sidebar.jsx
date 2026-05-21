import {
  Box,
  List,
  ListItemButton,
  ListItemText,
  Button,
  Typography,
  Divider,
  Select,
  MenuItem,
  FormControl,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";

const MODELS = [
  { key: "openai/gpt-4o-mini",              label: "GPT-4o mini" },
  { key: "openai/gpt-4o",                   label: "GPT-4o" },
  { key: "anthropic/claude-sonnet-4-6",     label: "Claude Sonnet 4.6" },
  { key: "anthropic/claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
];

function relativeTime(iso) {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default function Sidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  modelKey,
  onModelChange,
}) {
  return (
    <Box
      sx={{
        width: 260,
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
        borderRight: "1px solid #222",
        bgcolor: "#111",
      }}
    >
      <Box sx={{ p: 1.5, display: "flex", flexDirection: "column", gap: 1 }}>
        <FormControl size="small" fullWidth>
          <Select
            value={modelKey}
            onChange={(e) => onModelChange(e.target.value)}
            displayEmpty
            sx={{
              bgcolor: "#1a1a1a",
              color: "#ccc",
              fontSize: "0.8rem",
              borderRadius: 2,
              "& .MuiOutlinedInput-notchedOutline": { borderColor: "#333" },
              "&:hover .MuiOutlinedInput-notchedOutline": { borderColor: "#555" },
              "&.Mui-focused .MuiOutlinedInput-notchedOutline": { borderColor: "primary.main" },
              "& .MuiSvgIcon-root": { color: "#666" },
            }}
          >
            {MODELS.map((m) => (
              <MenuItem key={m.key} value={m.key} sx={{ fontSize: "0.85rem" }}>
                {m.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <Button
          fullWidth
          variant="outlined"
          startIcon={<AddIcon />}
          onClick={onNew}
          size="small"
          sx={{
            borderColor: "#333",
            color: "#aaa",
            justifyContent: "flex-start",
            borderRadius: 2,
            "&:hover": { borderColor: "#555", bgcolor: "#1a1a1a" },
          }}
        >
          New conversation
        </Button>
      </Box>

      <Divider sx={{ borderColor: "#222" }} />

      <List dense sx={{ flex: 1, overflowY: "auto", py: 0.5 }}>
        {conversations.length === 0 && (
          <Typography variant="body2" color="text.disabled" sx={{ px: 2, py: 1.5 }}>
            No conversations yet
          </Typography>
        )}
        {conversations.map((conv) => (
          <ListItemButton
            key={conv.id}
            selected={conv.id === activeId}
            onClick={() => onSelect(conv.id)}
            sx={{
              mx: 0.5,
              borderRadius: 1.5,
              mb: 0.25,
              "&.Mui-selected": { bgcolor: "#1e3a6e", "&:hover": { bgcolor: "#1e3a6e" } },
              "&:hover": { bgcolor: "#1a1a1a" },
            }}
          >
            <ListItemText
              primary={
                <Typography
                  variant="body2"
                  noWrap
                  sx={{ fontWeight: conv.id === activeId ? 600 : 400 }}
                >
                  {conv.title || "New conversation"}
                </Typography>
              }
              secondary={
                <Typography variant="caption" color="text.disabled" noWrap>
                  {conv.last_message
                    ? `${conv.last_message.slice(0, 40)}…`
                    : relativeTime(conv.updated_at)}
                </Typography>
              }
            />
          </ListItemButton>
        ))}
      </List>
    </Box>
  );
}
