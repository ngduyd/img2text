/**
 * Plan M4 — bộ extension Tiptap cho mode word, thay contenteditable + execCommand
 * (M3). HTML sinh ra phải khớp subset contract html_to_docx của server: p/heading,
 * strong/em/u, span style (font-size/font-family), ul/ol/li, table + text-align.
 */
import { Extension } from "@tiptap/core";
import type { Extensions } from "@tiptap/core";
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
];
