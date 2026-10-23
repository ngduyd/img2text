/**
 * Plan M4 — bộ extension Tiptap cho mode word, thay contenteditable + execCommand
 * (M3). HTML sinh ra phải khớp subset contract html_to_docx của server: p/heading,
 * strong/em/u, span style (font-size/font-family), ul/ol/li, table + text-align.
 */
import { Extension } from "@tiptap/core";
import type { Editor, Extensions } from "@tiptap/core";
import FontFamily from "@tiptap/extension-font-family";
import StarterKit from "@tiptap/starter-kit";
import Table from "@tiptap/extension-table";
import TableCell from "@tiptap/extension-table-cell";
import TableHeader from "@tiptap/extension-table-header";
import TableRow from "@tiptap/extension-table-row";
import TextAlign from "@tiptap/extension-text-align";
import TextStyle from "@tiptap/extension-text-style";
import Underline from "@tiptap/extension-underline";

/** Cỡ chữ 8-72 pt — select trên toolbar áp qua setMark('textStyle', { fontSize }). */
export const WORD_SIZES: number[] = Array.from({ length: 65 }, (_, i) => i + 8);

/**
 * Tiptap core KHÔNG có fontSize — attribute `fontSize` (đơn vị pt, dải 8-72 do
 * WORD_SIZES chặn ở toolbar) gắn vào mark textStyle, render/parse qua span style
 * giống wrap span của M3. Upgrade: slider/preset + clamp px khi nhận HTML ngoài dải.
 */
const FontSize = Extension.create({
  name: "fontSize",
  addGlobalAttributes() {
    return [
      {
        types: ["textStyle"],
        attributes: {
          fontSize: {
            default: null,
            parseHTML: (element) => (element as HTMLElement).style.fontSize || null,
            renderHTML: (attributes) =>
              attributes.fontSize ? { style: `font-size: ${attributes.fontSize}` } : {},
          },
        },
      },
    ];
  },
});

/**
 * Tier B (SPEC D9): attribute layout trên BLOCK (paragraph/heading) thay vì mark —
 * thụt lề + giãn dòng phải sống theo đoạn, và html_to_docx phía server đọc
 * `style="margin-left/line-height"` sẵn có trong contract.
 * ponytail: chỉ 2 thuộc tính, chưa cần extension thư viện; thêm letterSpacing/
 * textIndent khi có yêu cầu thật.
 */
function blockStyle(name: string, cssProp: string) {
  return Extension.create({
    name,
    addGlobalAttributes() {
      return [
        {
          types: ["paragraph", "heading"],
          attributes: {
            [name]: {
              default: null,
              parseHTML: (element) => (element as HTMLElement).style.getPropertyValue(cssProp) || null,
              renderHTML: (attributes) =>
                attributes[name] ? { style: `${cssProp}: ${attributes[name]}` } : {},
            },
          },
        },
      ];
    },
  });
}

export const Indent = blockStyle("indent", "margin-left");
export const LineHeight = blockStyle("lineHeight", "line-height");

/** Giãn dòng cho menu ▾ (giá trị css hợp lệ, không phải enum để khỏi map). */
export const LINE_HEIGHTS = ["1", "1.15", "1.5", "2"];

/** Áp 1 attribute layout cho MỌI block trong selection (không cần custom command). */
export function setBlockAttr(
  editor: Editor,
  name: "indent" | "lineHeight",
  value: string | null,
) {
  const { from, to } = editor.state.selection;
  editor
    .chain()
    .focus()
    .command(({ tr, state }) => {
      state.doc.nodesBetween(from, to, (node, pos) => {
        if (node.type.name === "paragraph" || node.type.name === "heading") {
          tr.setNodeAttribute(pos, name, value);
        }
      });
      return true;
    })
    .run();
}

/** Bước thụt lề (em) — đọc từ attr của block đầu tiên trong selection. */
export function currentIndent(editor: Editor): number {
  return Number(editor.getAttributes("paragraph").indent ?? 0) || 0;
}

/** Extensions dựng 1 lần (module singleton) — dùng bởi useEditor và test editor instance. */
export const wordExtensions: Extensions = [
  StarterKit,
  Underline,
  TextAlign.configure({ types: ["heading", "paragraph"] }),
  TextStyle,
  FontFamily,
  FontSize,
  Table.configure({ resizable: true }),
  TableRow,
  TableCell,
  TableHeader,
  Indent,
  LineHeight,
];
