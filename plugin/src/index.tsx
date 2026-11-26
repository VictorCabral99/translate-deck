import { definePlugin } from "@decky/api";
import { QAM } from "./QAM";

export default definePlugin(() => ({
  name: "Translate Deck",
  titleView: <div>Translate Deck</div>,
  content: <QAM />,
  icon: <span style={{ fontSize: "1.2em" }}>文</span>,
}));
