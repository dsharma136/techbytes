/**
 * Plain text for clipboard (matches card format: headline, blurb, why, sources).
 */
export function formatCardPlainText(card) {
  const lines = [
    card.headline ?? "",
    "",
    card.blurb ?? "",
    "",
    "WHY IT MATTERS",
    card.why_it_matters ?? "",
    "",
  ];
  const sources = Array.isArray(card.sources) ? card.sources : [];
  if (sources.length) {
    lines.push("SOURCES");
    for (const s of sources) {
      const t = s.title || "Link";
      const u = s.url || "";
      lines.push(u ? `${t} — ${u}` : t);
    }
  }
  lines.push("", "- TechBytes");
  return lines.filter(Boolean).join("\n").replace(/\n\n\n+/g, "\n\n");
}
