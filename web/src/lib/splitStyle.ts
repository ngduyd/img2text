/** Tách `<style>` khỏi HTML server trả về (preview dựng từ layout spec).

 * DOMPurify LUÔN bỏ thẻ `<style>` (kể cả ADD_TAGS) ⇒ CSS mất, mọi thứ dồn
 * 1 dòng/1 cột khi hiển thị trong iframe. Tách CSS trước khi sanitize rồi
 * nhúng lại vào srcDoc (CSS của server mình, không phải nội dung người dùng).
 */
export function splitStyle(html: string): { css: string; body: string } {
  const css: string[] = [];
  const body = html.replace(
    /<style[^>]*>([\s\S]*?)<\/style>/gi,
    (_m, c: string) => {
      css.push(c);
      return "";
    },
  );
  return { css: css.join("\n"), body };
}
