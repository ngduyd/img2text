import type { ReactNode } from "react";

/** 3 bậc container duy nhất của app (SPEC-ui-redesign D1):
 *  form  = 720px  — auth, Profile, Feedback
 *  data  = 1200px — Jobs, Storage, Admin, JobDetail, Extraction
 *  editor= 1200px — JobText/JobLayout (không padding ngang, page tự quản)
 */
const W = {
  form: "max-w-[720px]",
  data: "max-w-[1200px]",
  editor: "max-w-[1200px] px-0 py-0 sm:px-0",
} as const;

export default function PageShell({
  width = "data",
  testid,
  children,
}: {
  width?: keyof typeof W;
  testid?: string;
  children: ReactNode;
}) {
  const pad = width === "editor" ? "" : "px-4 py-6 sm:px-6";
  return (
    <main id="main" data-testid={testid} className={`mx-auto ${W[width]} ${pad}`}>
      {children}
    </main>
  );
}
