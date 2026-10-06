"use client";
import {useEffect, useRef, type ReactNode} from "react";

/** Layout only: selection, editing, provenance and persistence stay with each domain. */
export function ReviewWorkspaceLayout({actions, source, selector, beforeWorkspace, children}: {
  actions: ReactNode; source: ReactNode; selector: ReactNode;
  beforeWorkspace?: ReactNode; children: ReactNode;
}) {
  const root = useRef<HTMLDivElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const shell = root.current;
    const actions = bar.current;
    const header = document.querySelector<HTMLElement>(".header");
    if (!shell || !actions) return;
    const measure = () => {
      shell.style.setProperty("--review-header-height", `${header?.getBoundingClientRect().height || 0}px`);
      shell.style.setProperty("--review-actions-height", `${actions.getBoundingClientRect().height}px`);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(actions);
    if (header) observer.observe(header);
    return () => observer.disconnect();
  }, []);
  return <div className="review-workspace-shell" ref={root}>
    <div className="review-workspace-actions" ref={bar}>{actions}</div>
    {beforeWorkspace}
    <div className="review-workspace-columns">
      <aside className="review-workspace-source">{source}</aside>
      <div className="review-workspace-editor">
        <div className="review-workspace-selector">{selector}</div>
        <div className="review-workspace-body">{children}</div>
      </div>
    </div>
  </div>;
}
