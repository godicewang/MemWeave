/** Keep the advertised target unchanged; tolerate up to twice it at write time. */
export function assertStateContent(
  content: string,
  maxChars: number,
  field: string,
): void {
  const rejectionLimit = maxChars * 2;
  const actual = [...content].length;
  if (actual > rejectionLimit)
    throw Error(`STATE_CONTENT_TOO_LONG: field=${field}; actual=${actual}; max=${rejectionLimit} Unicode code points; shorten the content and retry`);
}
