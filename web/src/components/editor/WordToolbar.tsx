import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { Editor } from "@tiptap/core";
import { useEditorState } from "@tiptap/react";
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
import { WORD_SIZES } from "../../lib/wordEditor";
import Button from "../ui/Button";

/**
 * Plan M4: toolbar WORD 1 hàng (giữ nguyên testid word-tb-* + layout M3), mọi
 * lệnh chạy thẳng trên instance Tiptap (chain().focus(), áp THEO VÙN CHỌN —
 * Tiptap tự selection-based), không còn execCommand. Testid/HTML table picker
 * (grid 1-10×1-10) giữ nguyên.
 */

type ToggleKey = "bold" | "italic" | "underline" | "bulletList" | "orderedList";
type AlignValue = "left" | "center" | "right" | "justify";

interface UiState {
  bold: boolean;
  italic: boolean;
  underline: boolean;
  bulletList: boolean;
  orderedList: boolean;
  align: AlignValue;
  inTable: boolean;
  /** Giá trị hiện tại của mark textStyle (đã bỏ ngoặc/đơn vị) cho 2 select. */
  fontFamily: string;
  fontSize: string;
}

interface Item {
  testid: string;
  title: string;
  Icon: typeof Bold;
  run: (editor: Editor) => void;
  toggle?: ToggleKey;
  align?: AlignValue;
}

const CMD_GROUPS: Item[][] = [
  [
    { testid: "word-tb-undo", title: "Hoàn tác", Icon: Undo2, run: (e) => void e.commands.undo() },
    { testid: "word-tb-redo", title: "Làm lại", Icon: Redo2, run: (e) => void e.commands.redo() },
  ],
  [
    {
      testid: "word-tb-bold",
      title: "Đậm",
      Icon: Bold,
      toggle: "bold",
      run: (e) => void e.chain().focus().toggleBold().run(),
    },
    {
      testid: "word-tb-italic",
      title: "Nghiêng",
      Icon: Italic,
      toggle: "italic",
      run: (e) => void e.chain().focus().toggleItalic().run(),
    },
    {
      testid: "word-tb-underline",
      title: "Gạch chân",
      Icon: Underline,
      toggle: "underline",
      run: (e) => void e.chain().focus().toggleUnderline().run(),
    },
  ],
  [
    {
      testid: "word-tb-align-left",
      title: "Căn trái",
      Icon: AlignLeft,
      align: "left",
      run: (e) => void e.chain().focus().setTextAlign("left").run(),
    },
    {
      testid: "word-tb-align-center",
      title: "Căn giữa",
      Icon: AlignCenter,
      align: "center",
      run: (e) => void e.chain().focus().setTextAlign("center").run(),
    },
    {
      testid: "word-tb-align-right",
      title: "Căn phải",
      Icon: AlignRight,
      align: "right",
      run: (e) => void e.chain().focus().setTextAlign("right").run(),
    },
    {
      testid: "word-tb-align-justify",
      title: "Căn đều",
      Icon: AlignJustify,
      align: "justify",
      run: (e) => void e.chain().focus().setTextAlign("justify").run(),
    },
  ],
  [
    {
      testid: "word-tb-list-ul",
      title: "Danh sách chấm",
      Icon: List,
      toggle: "bulletList",
      run: (e) => void e.chain().focus().toggleBulletList().run(),
    },
    {
      testid: "word-tb-list-ol",
      title: "Danh sách số",
      Icon: ListOrdered,
      toggle: "orderedList",
      run: (e) => void e.chain().focus().toggleOrderedList().run(),
    },
  ],
  [
    {
      // removeFormat của M3 → bỏ mọi mark + đưa block về mặc định.
      testid: "word-tb-clear",
      title: "Xóa định dạng",
      Icon: Eraser,
      run: (e) => void e.chain().focus().unsetAllMarks().clearNodes().run(),
    },
  ],
];

const SELECT_CLS =
  "h-8 shrink-0 rounded-sm border border-border bg-surface px-2 text-sm text-text";

function Divider() {
  return <span aria-hidden="true" className="mx-1 h-5 w-px shrink-0 bg-border" />;
}

function CmdButton({
  editor,
  active,
  testid,
  title,
  run,
  children,
}: {
  editor: Editor | null;
  active?: boolean;
  testid: string;
  title: string;
  run: (editor: Editor) => void;
  children: ReactNode;
}) {
  return (
    <Button
      testid={testid}
      variant="ghost"
      size="sm"
      title={title}
      aria-label={title}
      aria-pressed={active}
      className={`shrink-0${active === true ? " bg-surface-2" : ""}`}
      // Giữ selection trong editor khi bấm toolbar (mất focus → mất caret).
      onMouseDown={(e) => e.preventDefault()}
      onClick={() => editor && run(editor)}
    >
      {children}
    </Button>
  );
}

function Group({
  items,
  editor,
  ui,
}: {
  items: Item[];
  editor: Editor | null;
  ui: UiState | null;
}) {
  return (
    <>
      {items.map(({ testid, title, Icon, run, toggle, align }) => (
        <CmdButton
          key={testid}
          editor={editor}
          testid={testid}
          title={title}
          run={run}
          active={
            ui === null ? undefined : toggle !== undefined ? ui[toggle] : align !== undefined ? ui.align === align : undefined
          }
        >
          <Icon className="h-4 w-4" aria-hidden="true" />
        </CmdButton>
      ))}
    </>
  );
}

export default function WordToolbar({ editor }: { editor: Editor | null }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [hover, setHover] = useState<{ r: number; c: number } | null>(null);

  // Re-render theo transaction: active state + cụm row/col trong bảng.
  const ui = useEditorState({
    editor,
    selector: ({ editor }): UiState | null => {
      if (!editor) return null;
      const style = editor.getAttributes("textStyle") as { fontFamily?: string; fontSize?: string };
      const align: AlignValue = editor.isActive({ textAlign: "center" })
        ? "center"
        : editor.isActive({ textAlign: "right" })
          ? "right"
          : editor.isActive({ textAlign: "justify" })
            ? "justify"
            : "left";
      return {
        bold: editor.isActive("bold"),
        italic: editor.isActive("italic"),
        underline: editor.isActive("underline"),
        bulletList: editor.isActive("bulletList"),
        orderedList: editor.isActive("orderedList"),
        align,
        inTable: editor.isActive("table"),
        fontFamily: (style.fontFamily ?? "").replace(/["']/g, ""),
        fontSize: (style.fontSize ?? "").replace(/pt$/, ""),
      };
    },
  });

  // Đóng grid picker khi bấm ra ngoài (Escape → blur cùng xử lý qua mousedown ngoài).
  useEffect(() => {
    if (!pickerOpen) return;
    const close = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setPickerOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [pickerOpen]);

  /** Áp textStyle (font/cỡ) = merge attrs hiện tại của selection — tránh mất attr kia. */
  const setTextStyle = (patch: { fontFamily?: string; fontSize?: string }) => {
    if (!editor) return;
    editor
      .chain()
      .focus()
      .setMark("textStyle", { ...editor.getAttributes("textStyle"), ...patch })
      .run();
  };

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
          <Group items={CMD_GROUPS[0]} editor={editor} ui={ui} />
          {divider}
          <select
            data-testid="word-tb-font"
            aria-label="Font chữ"
            title="Font chữ"
            className={SELECT_CLS}
            value={ui?.fontFamily ?? ""}
            onChange={(e) => e.target.value && setTextStyle({ fontFamily: e.target.value })}
          >
            <option value="">Font</option>
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
            value={ui?.fontSize ?? ""}
            onChange={(e) => e.target.value && setTextStyle({ fontSize: `${e.target.value}pt` })}
          >
            <option value="">Cỡ</option>
            {WORD_SIZES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {divider}
          <Group items={CMD_GROUPS[1]} editor={editor} ui={ui} />
          {divider}
          <Group items={CMD_GROUPS[2]} editor={editor} ui={ui} />
          {divider}
          <Group items={CMD_GROUPS[3]} editor={editor} ui={ui} />
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
          {divider}
          <Group items={CMD_GROUPS[4]} editor={editor} ui={ui} />
        </div>
        {/* Hàng 2: table row/col tách riêng — strip chính không quá ~15 control. */}
        {ui?.inTable && (
          <div
            data-testid="word-tb-table-controls"
            className="mt-2 flex items-center gap-2 whitespace-nowrap [&>*]:shrink-0"
          >
            <CmdButton
              editor={editor}
              testid="word-tb-row-add"
              title="Thêm hàng"
              run={(e) => void e.chain().focus().addRowAfter().run()}
            >
              + Hàng
            </CmdButton>
            <CmdButton
              editor={editor}
              testid="word-tb-row-del"
              title="Xóa hàng"
              run={(e) => void e.chain().focus().deleteRow().run()}
            >
              - Hàng
            </CmdButton>
            <CmdButton
              editor={editor}
              testid="word-tb-col-add"
              title="Thêm cột"
              run={(e) => void e.chain().focus().addColumnAfter().run()}
            >
              + Cột
            </CmdButton>
            <CmdButton
              editor={editor}
              testid="word-tb-col-del"
              title="Xóa cột"
              run={(e) => void e.chain().focus().deleteColumn().run()}
            >
              - Cột
            </CmdButton>
          </div>
        )}
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
                      editor?.chain().focus().insertTable({ rows: r, cols: c, withHeaderRow: true }).run();
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
