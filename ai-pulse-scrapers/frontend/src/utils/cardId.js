/**
 * Stable id for read progress and keys (API cards have no server id).
 */
export function stableCardId(feedDate, card, index) {
  if (card?.id != null && String(card.id).length > 0) {
    return String(card.id);
  }
  const order = card?.order ?? index;
  return `${feedDate ?? "unknown"}-${order}-${index}`;
}
