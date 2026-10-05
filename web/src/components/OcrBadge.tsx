import Badge from "./ui/Badge";

/** OCR status (single tone logic shared by App nav shell + Profile page, Task 3). */
export default function OcrBadge({
  enabled,
  testid = "badge-ocr",
}: {
  enabled: boolean;
  testid?: string;
}) {
  return enabled ? (
    <Badge tone="success" testid={testid}>
      OCR đã cấp
    </Badge>
  ) : (
    <Badge tone="warning" testid={testid}>
      Chờ admin cấp quyền
    </Badge>
  );
}
