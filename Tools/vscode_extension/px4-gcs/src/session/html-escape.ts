// Text to HTML for the session report. Everything that reaches the report from
// the vehicle (status text, console lines, parameter names) or from files goes
// through `escapeHtml`; the report has no script, so escaping is the only
// boundary between vehicle text and markup.

const ENTITIES: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export function escapeHtml(value: unknown): string {
  // Control characters (except tab and newline) are dropped: they have no visible form and some break parsers.
  // eslint-disable-next-line no-control-regex
  return String(value ?? '').replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, '').replace(/[&<>"']/g, (c) => ENTITIES[c]);
}

/** Tagged template: interpolated values are escaped, literal parts are markup. Use `raw()` for built markup. */
export function html(parts: TemplateStringsArray, ...values: unknown[]): Raw {
  let out = parts[0];
  values.forEach((value, i) => {
    out += (Array.isArray(value) ? value.map(markup).join('') : markup(value)) + parts[i + 1];
  });
  return new Raw(out);
}

export class Raw {
  constructor(readonly text: string) {}

  toString(): string {
    return this.text;
  }
}

export function raw(text: string): Raw {
  return new Raw(text);
}

function markup(value: unknown): string {
  return value instanceof Raw ? value.text : escapeHtml(value);
}
