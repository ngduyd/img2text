import { useEffect, useRef, useState } from "react";
import {
  AlignCenter,
  AlignJustify,
  AlignLeft,
  AlignRight,
  Bold,
  Eraser,
  Italic,
  List,
  ListOrdered,
  Redo2,
  Table2,
  Underline,
  Undo2,
} from "lucide-react";
import { FONT_FAMILIES } from "../../lib/docStyle";
import type { WordTableOp } from "../../lib/wordEditor";
import Button from "../ui/Button";

/**
 * Plan M3: toolbar WORD ĐỘI DUY NHẤT 1 hàng (overflow-x-auto khi tràn, gap-2,
 * sticky trong card) — mọi lệnh emit lên onCmd/onSize và được UnifiedEditor bắn
 * vào VÙN CHỌN của iframe (lib/wordEditor), không áp document. Testid word-tb-*
 * thuộc content toolbar; page-style controls của DocStyleTools = word-style-*.
 */

interface Item {
  cmd: string;
  testid: string;
  title: string;
  Icon: typeof Bold;
}

const CMD_GROUPS: Item[][] = [
  [
    { cmd: "undo", testid: "word-tb-undo", title: "Hoàn tác", Icon: Undo2 },
    { cmd: "redo", testid: "word-tb-redo", title: "Làm lại", Icon: Redo2 },
  ],
  [
    { cmd: "bold", testid: "word-tb-bold", title: "Đậm", Icon: Bold },
    { cmd: "italic", testid: "word-tb-italic", title: "Nghiêng", Icon: Italic },
    { cmd: "underline", testid: "word-tb-underline", title: "Gạch chân", Icon: Underline },
  ],
  [
    { cmd: "justifyLeft", testid: "word-tb-align-left", title: "Căn trái", Icon: AlignLeft },
    { cmd: "justifyCenter", testid: "word-tb-align-center", title: "Căn giữa", Icon: AlignCenter },
    { cmd: "justifyRight", testid: "word-tb-align-right", title: "Căn phải", Icon: AlignRight },
    { cmd: "justifyFull", testid: "word-tb-align-justify", title: "Căn đều", Icon: AlignJustify },
  ],
  [
    { cmd: "insertUnorderedList", testid: "word-tb-list-ul", title: "Danh sách chấm", Icon: List },
    {
      cmd: "insertOrderedList",
      testid: "word-tb-list-ol",
      title: "Danh sách số",
      Icon: ListOrdered,
    },
  ],
  [{ cmd: "removeFormat", testid: "word-tb-clear", title: "Xóa định dạng", Icon: Eraser }],
];

/** Cỡ chữ 8-72 pt (đơn vị pt như contract wrap span của lib/wordEditor). */
const SIZES = Array.from({ length: 65 }, (_, i) => i + 8);

const SELECT_CLS =
  "h-8 shrink-0 rounded-sm border border-border bg-surface px-2 text-sm text-text";

function Divider() {
  return <span aria-hidden="true" className="mx-1 h-5 w-px shrink-0 bg-border" />;
}

function Group({
  items,
  onCmd,
}: {
  items: Item[];
  onCmd: (cmd: string, arg?: string) => void;
}) {
  return (
    <>
      {items.map(({ cmd, testid, title, Icon }) => (
        <Button
          key={cmd}
          testid={testid}
          variant="ghost"
          size="sm"
          title={title}
          aria-label={title}
          className="shrink-0"
          // Giữ selection trong iframe khi bấm toolbar (mất focus → mất caret).
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => onCmd(cmd)}
        >
          <Icon className="h-4 w-4" aria-hidden="true" />
        </Button>
      ))}
    </>
  );
}

export default function WordToolbar({
  onCmd,
  onSize,
  onInsertTable,
  onTableOp,
  inTable,
}: {
  onCmd: (cmd: string, arg?: string) => void;
  onSize: (pt: number) => void;
  onInsertTable: (rows: number, cols: number) => void;
  onTableOp: (op: WordTableOp) => void;
  inTable: boolean;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [hover, setHover] = useState<{ r: number; c: number } | null>(null);

  // Đóng grid picker khi bấm ra ngoài (Escape → blur cùng xử lý qua mousedown ngoài).
  useEffect(() => {
    if (!pickerOpen) return;
    const close = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setPickerOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [pickerOpen]);

  const divider = <Divider />;

  return (
    <div
      ref={rootRef}
      data-testid="word-toolbar"
      className="sticky top-32 z-10 border-b border-border bg-surface py-2"
    >
      <div className="relative flex items-center gap-2">
        <div
          role="toolbar"
          aria-label="Công cụ soạn thảo Word"
          className="flex min-w-0 flex-1 items-center gap-2 overflow-x-auto whitespace-nowrap [&>*]:shrink-0"
        >
          <Group items={CMD_GROUPS[0]} onCmd={onCmd} />
          {divider}
          <select
            data-testid="word-tb-font"
            aria-label="Font chữ"
            title="Font chữ"
            className={SELECT_CLS}
            onChange={(e) => onCmd("fontName", e.target.value)}
          >
            {FONT_FAMILIES.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
          <select
            data-testid="word-tb-size"
            aria-label="Cỡ chữ (pt)"
            title="Cỡ chữ (pt)"
            className={SELECT_CLS}
            onChange={(e) => onSize(Number(e.target.value))}
          >
            {SIZES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {divider}
          <Group items={CMD_GROUPS[1]} onCmd={onCmd} />
          {divider}
          <Group items={CMD_GROUPS[2]} onCmd={onCmd} />
          {divider}
          <Group items={CMD_GROUPS[3]} onCmd={onCmd} />
          {divider}
          <Button
            testid="word-tb-table"
            variant="ghost"
            size="sm"
            title="Chèn bảng"
            aria-label="Chèn bảng"
            aria-expanded={pickerOpen}
            className="shrink-0"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => setPickerOpen((o) => !o)}
          >
            <Table2 className="h-4 w-4" aria-hidden="true" />
          </Button>
          {inTable && (
            <>
              <Button
                testid="word-tb-row-add"
                variant="ghost"
                size="sm"
                title="Thêm hàng"
                aria-label="Thêm hàng"
                className="shrink-0"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => onTableOp("row-add")}
              >
                + Hàng
              </Button>
              <Button
                testid="word-tb-row-del"
                variant="ghost"
                size="sm"
                title="Xóa hàng"
                aria-label="Xóa hàng"
                className="shrink-0"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => onTableOp("row-del")}
              >
                - Hàng
              </Button>
              <Button
                testid="word-tb-col-add"
                variant="ghost"
                size="sm"
                title="Thêm cột"
                aria-label="Thêm cột"
                className="shrink-0"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => onTableOp("col-add")}
              >
                + Cột
              </Button>
              <Button
                testid="word-tb-col-del"
                variant="ghost"
                size="sm"
                title="Xóa cột"
                aria-label="Xóa cột"
                className="shrink-0"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => onTableOp("col-del")}
              >
                - Cột
              </Button>
            </>
          )}
          {divider}
          <Group items={CMD_GROUPS[4]} onCmd={onCmd} />
        </div>
        {pickerOpen && (
          <div
            data-testid="word-tb-table-grid"
            className="absolute right-0 top-full z-20 mt-1 rounded-md border border-border bg-surface p-2 shadow-card"
          >
            <p className="mb-1 text-xs text-muted" aria-live="polite">
              {hover ? `Chèn bảng ${hover.r}×${hover.c}` : "Chọn bảng (tối đa 10×10)"}
            </p>
            <div className="grid grid-cols-10 gap-1">
              {Array.from({ length: 100 }, (_, i) => {
                const r = Math.floor(i / 10) + 1;
                const c = (i % 10) + 1;
                const active = hover !== null && r <= hover.r && c <= hover.c;
                return (
                  <button
                    key={i}
                    type="button"
                    data-testid={`word-tb-table-${r}x${c}`}
                    aria-label={`Chèn bảng ${r}×${c}`}
                    className={`h-3.5 w-3.5 rounded-sm border transition duration-150 ease-out ${
                      active
                        ? "border-accent bg-accent/40"
                        : "border-border bg-surface-2 hover:bg-surface"
                    }`}
                    onMouseEnter={() => setHover({ r, c })}
                    onFocus={() => setHover({ r, c })}
                    onClick={() => {
                      onInsertTable(r, c);
                      setPickerOpen(false);
                      setHover(null);
                    }}
                  />
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
