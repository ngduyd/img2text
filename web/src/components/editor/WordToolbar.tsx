import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { Editor } from "@tiptap/core";
import { useEditorState } from "@tiptap/react";
import {
  IndentDecrease,
  IndentIncrease,
  MoreHorizontal,
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
import {
  LINE_HEIGHTS,
  WORD_SIZES,
  currentIndent,
  setBlockAttr,
} from "../../lib/wordEditor";
import { useT } from "../../i18n";
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
  /** Tier B: block đang chọn đang là heading cấp nào (0 = paragraph). */
  heading: number;
  lineHeight: string;
}

interface Item {
  testid: string;
  titleKey: string;
  Icon: typeof Bold;
  run: (editor: Editor) => void;
  toggle?: ToggleKey;
  align?: AlignValue;
}

const CMD_GROUPS: Item[][] = [
  [
    { testid: "word-tb-undo", titleKey: "word.undo", Icon: Undo2, run: (e) => void e.commands.undo() },
    { testid: "word-tb-redo", titleKey: "word.redo", Icon: Redo2, run: (e) => void e.commands.redo() },
  ],
  [
    {
      testid: "word-tb-bold",
      titleKey: "word.bold",
      Icon: Bold,
      toggle: "bold",
      run: (e) => void e.chain().focus().toggleBold().run(),
    },
    {
      testid: "word-tb-italic",
      titleKey: "word.italic",
      Icon: Italic,
      toggle: "italic",
      run: (e) => void e.chain().focus().toggleItalic().run(),
    },
    {
      testid: "word-tb-underline",
      titleKey: "word.underline",
      Icon: Underline,
      toggle: "underline",
      run: (e) => void e.chain().focus().toggleUnderline().run(),
    },
  ],
  [
    {
      testid: "word-tb-align-left",
      titleKey: "word.alignLeft",
      Icon: AlignLeft,
      align: "left",
      run: (e) => void e.chain().focus().setTextAlign("left").run(),
    },
    {
      testid: "word-tb-align-center",
      titleKey: "word.alignCenter",
      Icon: AlignCenter,
      align: "center",
      run: (e) => void e.chain().focus().setTextAlign("center").run(),
    },
    {
      testid: "word-tb-align-right",
      titleKey: "word.alignRight",
      Icon: AlignRight,
      align: "right",
      run: (e) => void e.chain().focus().setTextAlign("right").run(),
    },
    {
      testid: "word-tb-align-justify",
      titleKey: "word.alignJustify",
      Icon: AlignJustify,
      align: "justify",
      run: (e) => void e.chain().focus().setTextAlign("justify").run(),
    },
  ],
  [
    {
      testid: "word-tb-list-ul",
      titleKey: "word.listUl",
      Icon: List,
      toggle: "bulletList",
      run: (e) => void e.chain().focus().toggleBulletList().run(),
    },
    {
      testid: "word-tb-list-ol",
      titleKey: "word.listOl",
      Icon: ListOrdered,
      toggle: "orderedList",
      run: (e) => void e.chain().focus().toggleOrderedList().run(),
    },
  ],
  [
    {
      // removeFormat của M3 → bỏ mọi mark + đưa block về mặc định.
      testid: "word-tb-clear",
      titleKey: "word.clearFormat",
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
  titleKey,
  run,
  children,
}: {
  editor: Editor | null;
  active?: boolean;
  testid: string;
  titleKey: string;
  run: (editor: Editor) => void;
  children: ReactNode;
}) {
  const { t } = useT();
  return (
    <Button
      testid={testid}
      variant="ghost"
      size="sm"
      title={t(titleKey)}
      aria-label={t(titleKey)}
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
      {items.map(({ testid, titleKey, Icon, run, toggle, align }) => (
        <CmdButton
          key={testid}
          editor={editor}
          testid={testid}
          titleKey={titleKey}
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
  const { t } = useT();
  const rootRef = useRef<HTMLDivElement>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [indent, setIndent] = useState(0);
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
        heading: [1, 2, 3].find((l) => editor.isActive("heading", { level: l })) ?? 0,
        lineHeight: String(editor.getAttributes("paragraph").lineHeight ?? ""),
      };
    },
  });

  // Đóng grid picker / menu ▾ khi bấm ra ngoài (Escape → blur cùng xử lý qua mousedown ngoài).
  useEffect(() => {
    if (!pickerOpen && !moreOpen) return;
    const close = (e: MouseEvent) => {
      if (rootRef.current?.contains(e.target as Node)) return;
      setPickerOpen(false);
      setMoreOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setPickerOpen(false);
      setMoreOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", onKey);
    };
  }, [pickerOpen, moreOpen]);

  // Thụt lề hiện tại của block đầu selection (attr đọc từ editor, không state riêng).
  useEffect(() => {
    if (!editor) return;
    const sync = () => setIndent(currentIndent(editor));
    sync();
    editor.on("selectionUpdate", sync);
    editor.on("transaction", sync);
    return () => {
      editor.off("selectionUpdate", sync);
      editor.off("transaction", sync);
    };
  }, [editor]);

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
      className="lg:sticky lg:top-32 z-10 border-b border-border bg-surface py-2"
    >
      <div className="relative flex items-center gap-2">
        <div
          role="toolbar"
          aria-label={t("word.toolbarAria")}
          className="flex min-w-0 flex-1 items-center gap-2 overflow-x-auto whitespace-nowrap [&>*]:shrink-0"
        >
          <Group items={CMD_GROUPS[0]} editor={editor} ui={ui} />
          {divider}
          <select
            data-testid="word-tb-font"
            aria-label={t("word.font")}
            title={t("word.font")}
            className={SELECT_CLS}
            value={ui?.fontFamily ?? ""}
            onChange={(e) => e.target.value && setTextStyle({ fontFamily: e.target.value })}
          >
            <option value="">{t("word.fontOption")}</option>
            {FONT_FAMILIES.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
          <select
            data-testid="word-tb-size"
            aria-label={t("word.size")}
            title={t("word.size")}
            className={SELECT_CLS}
            value={ui?.fontSize ?? ""}
            onChange={(e) => e.target.value && setTextStyle({ fontSize: `${e.target.value}pt` })}
          >
            <option value="">{t("word.sizeOption")}</option>
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
            title={t("word.insertTable")}
            aria-label={t("word.insertTable")}
            aria-expanded={pickerOpen}
            className="shrink-0"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => setPickerOpen((o) => !o)}
          >
            <Table2 className="h-4 w-4" aria-hidden="true" />
          </Button>
          {divider}
          <Group items={CMD_GROUPS[4]} editor={editor} ui={ui} />
          {divider}
          {/* D9: phần còn lại (tier B) nằm trong ▾ — toolbar giữ 1 hàng. */}
          <Button
            testid="word-tb-more"
            variant="ghost"
            size="sm"
            title={t("word.moreTools")}
            aria-label={t("word.moreTools")}
            aria-expanded={moreOpen}
            aria-controls="word-tb-more-panel"
            className="shrink-0"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => setMoreOpen((o) => !o)}
          >
            <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
        {moreOpen && (
          <div
            id="word-tb-more-panel"
            data-testid="word-tb-more-panel"
            className="absolute right-0 top-full z-20 mt-1 flex w-56 flex-col gap-2 rounded-md border border-border bg-surface p-2 shadow-card"
          >
            <label className="flex items-center justify-between gap-2 text-sm text-muted">
              {t("word.paragraph")}
              <select
                data-testid="word-tb-heading"
                aria-label={t("word.paragraph")}
                className={SELECT_CLS}
                value={String(ui?.heading ?? 0)}
                onChange={(e) => {
                  if (!editor) return;
                  const level = Number(e.target.value);
                  if (level === 0) editor.chain().focus().setParagraph().run();
                  else editor.chain().focus().setHeading({ level: level as 1 | 2 | 3 }).run();
                }}
              >
                <option value="0">{t("word.paragraph")}</option>
                <option value="1">H1</option>
                <option value="2">H2</option>
                <option value="3">H3</option>
              </select>
            </label>
            <label className="flex items-center justify-between gap-2 text-sm text-muted">
              {t("word.lineHeight")}
              <select
                data-testid="word-tb-line-height"
                aria-label={t("word.lineHeight")}
                className={SELECT_CLS}
                value={ui?.lineHeight || ""}
                onChange={(e) => editor && setBlockAttr(editor, "lineHeight", e.target.value || null)}
              >
                <option value="">{t("word.lineHeightDefault")}</option>
                {LINE_HEIGHTS.map((h) => (
                  <option key={h} value={h}>
                    {h}
                  </option>
                ))}
              </select>
            </label>
            <div className="flex items-center gap-1">
              <CmdButton
                editor={editor}
                testid="word-tb-indent"
                titleKey="word.indent"
                run={(e) => setBlockAttr(e, "indent", `${Math.min(indent + 2, 16)}em`)}
              >
                <IndentIncrease className="h-4 w-4" aria-hidden="true" />
              </CmdButton>
              <CmdButton
                editor={editor}
                testid="word-tb-outdent"
                titleKey="word.outdent"
                run={(e) => {
                  const next = Math.max(indent - 2, 0);
                  setBlockAttr(e, "indent", next === 0 ? null : `${next}em`);
                }}
              >
                <IndentDecrease className="h-4 w-4" aria-hidden="true" />
              </CmdButton>
            </div>
          </div>
        )}
        {/* Hàng 2: table row/col tách riêng — strip chính không quá ~15 control. */}
        {ui?.inTable && (
          <div
            data-testid="word-tb-table-controls"
            className="mt-2 flex items-center gap-2 whitespace-nowrap [&>*]:shrink-0"
          >
            <CmdButton
              editor={editor}
              testid="word-tb-row-add"
              titleKey="word.addRow"
              run={(e) => void e.chain().focus().addRowAfter().run()}
            >
              + {t("word.row")}
            </CmdButton>
            <CmdButton
              editor={editor}
              testid="word-tb-row-del"
              titleKey="word.delRow"
              run={(e) => void e.chain().focus().deleteRow().run()}
            >
              - {t("word.row")}
            </CmdButton>
            <CmdButton
              editor={editor}
              testid="word-tb-col-add"
              titleKey="word.addCol"
              run={(e) => void e.chain().focus().addColumnAfter().run()}
            >
              + {t("word.col")}
            </CmdButton>
            <CmdButton
              editor={editor}
              testid="word-tb-col-del"
              titleKey="word.delCol"
              run={(e) => void e.chain().focus().deleteColumn().run()}
            >
              - {t("word.col")}
            </CmdButton>
          </div>
        )}
        {pickerOpen && (
          <div
            data-testid="word-tb-table-grid"
            className="absolute right-0 top-full z-20 mt-1 rounded-md border border-border bg-surface p-2 shadow-card"
          >
            <p className="mb-1 text-xs text-muted" aria-live="polite">
              {hover
                ? t("word.tableInsert", { r: hover.r, c: hover.c })
                : t("word.tablePick")}
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
                    aria-label={t("word.tableInsert", { r, c })}
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
