import { ThemeToggle } from "./ThemeToggle";

/** The mark and the name, as in the header. */
export function BrandMark() {
  return (
    <>
      <img src="/logo.svg" alt="" width="34" height="34" className="brand-mark" />
      <span>Sahifa</span>
      <span className="brand-ar" lang="ar" dir="rtl" aria-hidden="true">
        صحيفة
      </span>
    </>
  );
}

/** Frame of the pages outside the signed-in app (sign-in, no access): the mark, the theme
 * toggle and one narrow card. */
export function PlainFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="app">
      <div className="topbar">
        <header className="wrap site-header">
          <span className="brand">
            <BrandMark />
          </span>
          <ThemeToggle />
        </header>
      </div>
      <main id="main" className="wrap main" tabIndex={-1}>
        <div className="card auth-card stack">{children}</div>
      </main>
    </div>
  );
}
