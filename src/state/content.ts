/** Count Unicode code points, matching the existing State content contract. */
export function assertStateContent(
  content: string,
  maxChars: number,
  field: string,
): void {
  const actual = [...content].length;
  if (actual > maxChars)
    throw Error(`STATE_CONTENT_TOO_LONG: field=${field}; actual=${actual}; max=${maxChars} Unicode code points; shorten the content and retry`);
}
