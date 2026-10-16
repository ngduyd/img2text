import type { ReactNode } from "react";

const W = { content: "max-w-3xl", wide: "max-w-6xl" } as const;

export default function PageShell({
  width = "content",
  testid,
  children,
}: {
  width?: keyof typeof W;
  testid?: string;
  children: ReactNode;
}) {
  return (
    <main id="main" data-testid={testid} className={`mx-auto ${W[width]} px-4 py-6 sm:px-6`}>
      {children}
    </main>
  );
}
