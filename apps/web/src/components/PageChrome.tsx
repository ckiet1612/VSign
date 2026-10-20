import type { ReactNode } from "react";
import type { Icon } from "../icons";

// Dashboard-style page header shared by every workspace tab: large title, section tabs and refresh on the right.
export function PageHero({ title, titleId = "workspace-page-title", children }: {
  title: string;
  titleId?: string;
  children?: ReactNode;
}) {
  return (
    <header className="workspace-page-header">
      <h1 id={titleId}>{title}</h1>
      {children && <div className="workspace-page-actions">{children}</div>}
    </header>
  );
}

// Card heading: Mage icon, muted title and optional trailing content, as on the dashboard cards.
export function CardHead({ icon: Glyph, id, title, children }: {
  icon: Icon;
  id?: string;
  title: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="page-card-head">
      <span className="page-card-title"><Glyph size={18} aria-hidden="true" /><h2 id={id}>{title}</h2></span>
      {children}
    </div>
  );
}
