import { Fragment } from "react";
import {
  Bold,
  Code,
  Heading1,
  Heading2,
  Heading3,
  Italic,
  Link2,
  List,
  Quote,
  Redo2,
  Strikethrough,
  Table2,
  Undo2,
} from "lucide-react";
import Button from "../ui/Button";
import type { MdFormatOp } from "./mdFormat";

/**
 * Toolbar MD thuần UI: emit `onFormat(op, arg?)`, KHÔNG đọc/ghi textarea —
 * parent (job detail) tự wire selection + `applyMdOp`. Link prompt URL ở đây
 * vì đây là UI concern thuần (không đụng DOM editor).
 */
interface Item {
  op: MdFormatOp;
  title: string;
  Icon: typeof Bold;
}

const GROUPS: Item[][] = [
  [
    { op: "undo", title: "Hoàn tác", Icon: Undo2 },
    { op: "redo", title: "Làm lại", Icon: Redo2 },
  ],
  [
    { op: "h1", title: "Heading 1", Icon: Heading1 },
    { op: "h2", title: "Heading 2", Icon: Heading2 },
    { op: "h3", title: "Heading 3", Icon: Heading3 },
  ],
  [
    { op: "bold", title: "Đậm", Icon: Bold },
    { op: "italic", title: "Nghiêng", Icon: Italic },
    { op: "strike", title: "Gạch ngang", Icon: Strikethrough },
  ],
  [
    { op: "list", title: "Danh sách", Icon: List },
    { op: "quote", title: "Trích dẫn", Icon: Quote },
    { op: "code", title: "Khối mã", Icon: Code },
  ],
  [
    { op: "link", title: "Liên kết", Icon: Link2 },
    { op: "table", title: "Chèn bảng", Icon: Table2 },
  ],
];

export default function MdToolbar({
  onFormat,
}: {
  onFormat: (op: MdFormatOp, arg?: string) => void;
}) {
  function handleClick(op: MdFormatOp) {
    if (op === "link") {
      const url = window.prompt("Đường dẫn URL", "https://");
      if (!url) return;
      onFormat("link", url);
      return;
    }
    onFormat(op);
  }

  return (
    /* Plan M3: md toolbar 1 hàng duy nhất — tràn thì scroll ngang (giữ logic md nguyên). */
    <div
      role="toolbar"
      aria-label="Công cụ Markdown"
      className="flex items-center gap-1 overflow-x-auto whitespace-nowrap [&>*]:shrink-0"
    >
      {GROUPS.map((group, gi) => (
        <Fragment key={gi}>
          {gi > 0 && <span aria-hidden="true" className="mx-1 h-5 w-px bg-border" />}
          {group.map(({ op, title, Icon }) => (
            <Button
              key={op}
              testid={`md-tb-${op}`}
              variant="ghost"
              size="sm"
              title={title}
              aria-label={title}
              onClick={() => handleClick(op)}
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
            </Button>
          ))}
        </Fragment>
      ))}
    </div>
  );
}
