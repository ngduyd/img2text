/** paged.js không kèm type — chỉ khai báo phần PagePreview dùng (D7). */
declare module "pagedjs" {
  export class Previewer {
    preview(
      content: string,
      stylesheets?: (string | Record<string, string>)[],
      renderTo?: HTMLElement,
    ): Promise<{ total: number }>;
  }
}
