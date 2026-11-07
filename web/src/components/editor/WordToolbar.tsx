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
  ChevronDown,
  Eraser,
  IndentDecrease,
  IndentIncrease,
  Italic,
  List,
  ListOrdered,
  MoreHorizontal,
  PanelBottom,
  PanelLeft,
  PanelRight,
  PanelTop,
  Pilcrow,
  SlidersHorizontal,
  Table2,
  Underline,
  Undo2,
  Redo2,
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
 * Toolbar WORD — nhóm theo phương án A (2026-11-07):
 *   [Đoạn văn▾][Font▾][Size▾] │ [B][I][U] │ [Căn lề▾][Danh sách▾] │ [Bảng][Trang][⋯]
 * Align 4 nút + list 2 nút gộp thành 1 dropdown mỗi cái (tiết kiệm ~200px); nội
 * dung còn lại (clear/line-height/indent) + chọn vị trí dock nằm trong ⋯.
 *
 * `pageTools` = khối Page & text style (DocStyleTools) do UnifiedEditor sở hữu
 * state, được bơm vào popover "Trang" — trước đây nó là <details> dưới tờ giấy.
 *
 * Dock trái/phải: select không xếp dọc được → gộp 3 select vào popover "Định dạng".
 */

export type Dock = "top" | "bottom" | "left" | "right";

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
  fontFamily: string;
  fontSize: string;
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

const HISTORY: Item[] = [
  { testid: "word-tb-undo", titleKey: "word.undo", Icon: Undo2, run: (e) => void e.commands.undo() },
  { testid: "word-tb-redo", titleKey: "word.redo", Icon: Redo2, run: (e) => void e.commands.redo() },
];

const MARKS: Item[] = [
  { testid: "word-tb-bold", titleKey: "word.bold", Icon: Bold, toggle: "bold", run: (e) => void e.chain().focus().toggleBold().run() },
  { testid: "word-tb-italic", titleKey: "word.italic", Icon: Italic, toggle: "italic", run: (e) => void e.chain().focus().toggleItalic().run() },
  { testid: "word-tb-underline", titleKey: "word.underline", Icon: Underline, toggle: "underline", run: (e) => void e.chain().focus().toggleUnderline().run() },
];

const ALIGNS: Item[] = [
  { testid: "word-tb-align-left", titleKey: "word.alignLeft", Icon: AlignLeft, align: "left", run: (e) => void e.chain().focus().setTextAlign("left").run() },
  { testid: "word-tb-align-center", titleKey: "word.alignCenter", Icon: AlignCenter, align: "center", run: (e) => void e.chain().focus().setTextAlign("center").run() },
  { testid: "word-tb-align-right", titleKey: "word.alignRight", Icon: AlignRight, align: "right", run: (e) => void e.chain().focus().setTextAlign("right").run() },
  { testid: "word-tb-align-justify", titleKey: "word.alignJustify", Icon: AlignJustify, align: "justify", run: (e) => void e.chain().focus().setTextAlign("justify").run() },
];

const LISTS: Item[] = [
  { testid: "word-tb-list-ul", titleKey: "word.listUl", Icon: List, toggle: "bulletList", run: (e) => void e.chain().focus().toggleBulletList().run() },
  { testid: "word-tb-list-ol", titleKey: "word.listOl", Icon: ListOrdered, toggle: "orderedList", run: (e) => void e.chain().focus().toggleOrderedList().run() },
];

const DOCK_ICON: Record<Dock, typeof PanelTop> = {
  top: PanelTop,
  bottom: PanelBottom,
  left: PanelLeft,
  right: PanelRight,
};

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

function Group({ items, editor, ui }: { items: Item[]; editor: Editor | null; ui: UiState | null }) {
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
            ui === null
              ? undefined
              : toggle !== undefined
                ? ui[toggle]
                : align !== undefined
                  ? ui.align === align
                  : undefined
          }
        >
          <Icon className="h-4 w-4" aria-hidden="true" />
        </CmdButton>
      ))}
    </>
  );
}

/** Dropdown 1 nút cho nhóm lệnh cùng loại (thay 4 nút align / 2 nút list). */
function Dropdown({
  editor,
  ui,
  testid,
  titleKey,
  FallbackIcon,
  items,
  activeOf,
  open,
  onToggle,
  vertical,
}: {
  editor: Editor | null;
  ui: UiState | null;
  testid: string;
  titleKey: string;
  FallbackIcon: typeof Bold;
  items: Item[];
  activeOf: (i: Item) => boolean;
  open: boolean;
  onToggle: () => void;
  vertical: boolean;
}) {
  const { t } = useT();
  const Active = items.find(activeOf)?.Icon ?? FallbackIcon;
  return (
    <div className="relative shrink-0">
      <Button
        testid={testid}
        variant="ghost"
        size="sm"
        title={t(titleKey)}
        aria-label={t(titleKey)}
        aria-expanded={open}
        className={`shrink-0${open ? " bg-surface-2" : ""}`}
        onMouseDown={(e) => e.preventDefault()}
        onClick={onToggle}
      >
        <Active className="h-4 w-4" aria-hidden="true" />
        <ChevronDown className="ml-0.5 h-3 w-3" aria-hidden="true" />
      </Button>
      {open && (
        <div
          className={`absolute z-20 mt-1 flex gap-1 rounded-md border border-border bg-surface p-1 shadow-card ${
            vertical ? "left-full top-0 ml-1 mt-0 flex-col" : "left-0 top-full"
          }`}
        >
          {items.map((item) => {
            const { testid: id, titleKey: tk, Icon, run } = item;
            return (
              <CmdButton
                key={id}
                editor={editor}
                testid={id}
                titleKey={tk}
                run={run}
                active={ui === null ? undefined : activeOf(item)}
              >
                <Icon className="h-4 w-4" aria-hidden="true" />
              </CmdButton>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function WordToolbar({
  editor,
  dock = "top",
  onDockChange,
  pageTools,
}: {
  editor: Editor | null;
  dock?: Dock;
  onDockChange?: (d: Dock) => void;
  pageTools?: ReactNode;
}) {
  const { t } = useT();
  const rootRef = useRef<HTMLDivElement>(null);
  const [openMenu, setOpenMenu] = useState<null | "align" | "list" | "table" | "page" | "more" | "format">(null);
  const [hover, setHover] = useState<{ r: number; c: number } | null>(null);
  const [indent, setIndent] = useState(0);
  const vertical = dock === "left" || dock === "right";

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

  // Đóng mọi popover khi bấm ra ngoài / Escape (grid picker dùng chung state này).
  useEffect(() => {
    if (openMenu === null) return;
    const close = (e: MouseEvent) => {
      if (rootRef.current?.contains(e.target as Node)) return;
      setOpenMenu(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpenMenu(null);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", onKey);
    };
  }, [openMenu]);

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

  const setTextStyle = (patch: { fontFamily?: string; fontSize?: string }) => {
    if (!editor) return;
    editor
      .chain()
      .focus()
      .setMark("textStyle", { ...editor.getAttributes("textStyle"), ...patch })
      .run();
  };

  const headingSelect = (
    <select
      data-testid="word-tb-heading"
      aria-label={t("word.paragraph")}
      title={t("word.paragraph")}
      className={SELECT_CLS}
      value={String(ui?.heading ?? 0)}
      onChange={(e) => {
        if (!editor) return;
        const level = Number(e.target.value);
        if (level === 0) editor.chain().focus().setParagraph().run();
        else editor.chain().focus().setHeading({ level: level as 1 | 2 | 3 }).run();
      }}
    >
      <option value="0">{t("word.normalText")}</option>
      <option value="1">H1</option>
      <option value="2">H2</option>
      <option value="3">H3</option>
    </select>
  );
  const fontSelect = (
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
  );
  const sizeSelect = (
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
  );

  return (
    <div
      ref={rootRef}
      data-testid="word-toolbar"
      data-dock={dock}
      className="relative z-10 border-border bg-surface"
    >
      <div className={vertical ? "flex flex-col items-center gap-1 py-1" : "flex items-center gap-2 py-1"}>
        <div
          role="toolbar"
          aria-label={t("word.toolbarAria")}
          className={
            vertical
              ? "flex min-w-0 flex-col items-center gap-2 overflow-y-auto [&>*]:shrink-0"
              : "flex min-w-0 flex-1 items-center gap-2 overflow-x-auto whitespace-nowrap [&>*]:shrink-0"
          }
        >
          {/* Dock trái/phải: 3 select không xếp dọc được → gộp vào 1 popover. */}
          {vertical ? (
            <div className="relative">
              <Button
                testid="word-tb-format"
                variant="ghost"
                size="sm"
                title={t("word.formatGroup")}
                aria-label={t("word.formatGroup")}
                aria-expanded={openMenu === "format"}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => setOpenMenu((m) => (m === "format" ? null : "format"))}
              >
                <Pilcrow className="h-4 w-4" aria-hidden="true" />
              </Button>
              {openMenu === "format" && (
                <div className="absolute left-full top-0 z-30 ml-1 flex w-52 flex-col gap-2 rounded-md border border-border bg-surface p-2 shadow-card">
                  {headingSelect}
                  {fontSelect}
                  {sizeSelect}
                </div>
              )}
            </div>
          ) : (
            <>
              {headingSelect}
              {Divider()}
              {fontSelect}
              {sizeSelect}
              {Divider()}
            </>
          )}

          <Group items={HISTORY} editor={editor} ui={ui} />
          {Divider()}
          <Group items={MARKS} editor={editor} ui={ui} />
          {Divider()}
          <Dropdown
            editor={editor}
            ui={ui}
            testid="word-tb-align"
            titleKey="word.alignGroup"
            FallbackIcon={AlignLeft}
            items={ALIGNS}
            activeOf={(i) => ui !== null && i.align !== undefined && ui.align === i.align}
            open={openMenu === "align"}
            onToggle={() => setOpenMenu((m) => (m === "align" ? null : "align"))}
            vertical={vertical}
          />
          <Dropdown
            editor={editor}
            ui={ui}
            testid="word-tb-list"
            titleKey="word.listGroup"
            FallbackIcon={List}
            items={LISTS}
            activeOf={(i) => ui !== null && i.toggle !== undefined && ui[i.toggle] === true}
            open={openMenu === "list"}
            onToggle={() => setOpenMenu((m) => (m === "list" ? null : "list"))}
            vertical={vertical}
          />
          {Divider()}
          <Button
            testid="word-tb-table"
            variant="ghost"
            size="sm"
            title={t("word.insertTable")}
            aria-label={t("word.insertTable")}
            aria-expanded={openMenu === "table"}
            className="shrink-0"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => setOpenMenu((m) => (m === "table" ? null : "table"))}
          >
            <Table2 className="h-4 w-4" aria-hidden="true" />
          </Button>
          {pageTools && (
            <Button
              testid="word-tb-page"
              variant="ghost"
              size="sm"
              title={t("word.pageTools")}
              aria-label={t("word.pageTools")}
              aria-expanded={openMenu === "page"}
              className={`shrink-0${openMenu === "page" ? " bg-surface-2" : ""}`}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => setOpenMenu((m) => (m === "page" ? null : "page"))}
            >
              <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
            </Button>
          )}
          <Button
            testid="word-tb-more"
            variant="ghost"
            size="sm"
            title={t("word.moreTools")}
            aria-label={t("word.moreTools")}
            aria-expanded={openMenu === "more"}
            aria-controls="word-tb-more-panel"
            className={`shrink-0${openMenu === "more" ? " bg-surface-2" : ""}`}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => setOpenMenu((m) => (m === "more" ? null : "more"))}
          >
            <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
      </div>

      {/* ── Popover: Page & text style ────────────────────────────── */}
      {openMenu === "page" && pageTools && (
        <div
          data-testid="word-tb-page-panel"
          className="absolute right-0 top-full z-30 mt-1 w-72 rounded-md border border-border bg-surface p-3 shadow-card"
        >
          {pageTools}
        </div>
      )}

      {/* ── Popover: ⋯ (văn bản + vị trí toolbar) ─────────────────── */}
      {openMenu === "more" && (
        <div
          id="word-tb-more-panel"
          data-testid="word-tb-more-panel"
          className="absolute right-0 top-full z-30 mt-1 flex w-60 flex-col gap-2 rounded-md border border-border bg-surface p-2 shadow-card"
        >
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
            <span aria-hidden="true" className="mx-1 h-5 w-px bg-border" />
            <CmdButton
              editor={editor}
              testid="word-tb-clear"
              titleKey="word.clearFormat"
              run={(e) => void e.chain().focus().unsetAllMarks().clearNodes().run()}
            >
              <Eraser className="h-4 w-4" aria-hidden="true" />
            </CmdButton>
          </div>
          {onDockChange && (
            <div className="border-t border-border pt-2">
              <p className="mb-1 text-xs text-muted">{t("word.dockPosition")}</p>
              <div
                role="group"
                aria-label={t("word.dockPosition")}
                className="flex items-center gap-1"
              >
                {(["top", "bottom", "left", "right"] as Dock[]).map((d) => {
                  const Icon = DOCK_ICON[d];
                  return (
                    <Button
                      key={d}
                      testid={`word-tb-dock-${d}`}
                      variant="ghost"
                      size="sm"
                      title={t(`word.dock.${d}`)}
                      aria-label={t(`word.dock.${d}`)}
                      aria-pressed={dock === d}
                      className={dock === d ? "bg-surface-2" : ""}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => onDockChange(d)}
                    >
                      <Icon className="h-4 w-4" aria-hidden="true" />
                    </Button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Grid chèn bảng ────────────────────────────────────────── */}
      {openMenu === "table" && (
        <div
          data-testid="word-tb-table-grid"
          className="absolute right-0 top-full z-30 mt-1 rounded-md border border-border bg-surface p-2 shadow-card"
        >
          <p className="mb-1 text-xs text-muted" aria-live="polite">
            {hover ? t("word.tableInsert", { r: hover.r, c: hover.c }) : t("word.tablePick")}
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
                    active ? "border-accent bg-accent/40" : "border-border bg-surface-2 hover:bg-surface"
                  }`}
                  onMouseEnter={() => setHover({ r, c })}
                  onFocus={() => setHover({ r, c })}
                  onClick={() => {
                    editor
                      ?.chain()
                      .focus()
                      .insertTable({ rows: r, cols: c, withHeaderRow: true })
                      .run();
                    setOpenMenu(null);
                    setHover(null);
                  }}
                />
              );
            })}
          </div>
        </div>
      )}

      {/* ── Hàng ngữ cảnh: thao tác trong bảng ───────────────────── */}
      {ui?.inTable && (
        <div
          data-testid="word-tb-table-controls"
          className="flex items-center gap-2 whitespace-nowrap border-t border-border px-2 py-1 [&>*]:shrink-0"
        >
          <CmdButton editor={editor} testid="word-tb-row-add" titleKey="word.addRow" run={(e) => void e.chain().focus().addRowAfter().run()}>
            + {t("word.row")}
          </CmdButton>
          <CmdButton editor={editor} testid="word-tb-row-del" titleKey="word.delRow" run={(e) => void e.chain().focus().deleteRow().run()}>
            - {t("word.row")}
          </CmdButton>
          <CmdButton editor={editor} testid="word-tb-col-add" titleKey="word.addCol" run={(e) => void e.chain().focus().addColumnAfter().run()}>
            + {t("word.col")}
          </CmdButton>
          <CmdButton editor={editor} testid="word-tb-col-del" titleKey="word.delCol" run={(e) => void e.chain().focus().deleteColumn().run()}>
            - {t("word.col")}
          </CmdButton>
        </div>
      )}
    </div>
  );
}
