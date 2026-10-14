import Badge from "./ui/Badge";
import { useT } from "../i18n";

/** OCR status (single tone logic shared by App nav shell + Profile page, Task 3). */
export default function OcrBadge({
  enabled,
  testid = "badge-ocr",
}: {
  enabled: boolean;
  testid?: string;
}) {
  const { t } = useT();
  return enabled ? (
    <Badge tone="success" testid={testid}>
      {t("ocr.enabled")}
    </Badge>
  ) : (
    <Badge tone="warning" testid={testid}>
      {t("ocr.pending")}
    </Badge>
  );
}
