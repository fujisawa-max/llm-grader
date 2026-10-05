import Link from "next/link";

type Props = {
  description: string;
  label: string;
  compact?: boolean;
} & ({href: string; onAction?: never} | {onAction: () => void; href?: never});

export function NextActionPanel({description, label, compact = false, href, onAction}: Props) {
  return <section className={`next-action${compact ? " compact" : ""}`} aria-label="次に行う作業">
    <div><h2>次に行う作業</h2><p>{description}</p></div>
    {href !== undefined
      ? <Link className="button" href={href}>{label} ›</Link>
      : <button className="button" type="button" onClick={onAction}>{label} ›</button>}
  </section>;
}
