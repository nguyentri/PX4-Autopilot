// The only way the dashboard puts data on the page: elements are built from
// fixed tag and attribute names, and every vehicle-supplied string becomes a
// text node (plan decision D6). No markup string is ever parsed.

type Child = Node | string | null | undefined | false;

export interface ElementOptions {
  className?: string;
  text?: string;
  attrs?: Record<string, string>;
  title?: string;
}

const SVG_NS = 'http://www.w3.org/2000/svg';

function fill(node: Element, options: ElementOptions, children: Child[]): void {
  if (options.className) node.setAttribute('class', options.className);
  if (options.title) node.setAttribute('title', options.title);
  for (const [name, value] of Object.entries(options.attrs ?? {})) node.setAttribute(name, value);
  if (options.text !== undefined) node.textContent = options.text;
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
  }
}

export function el<K extends keyof HTMLElementTagNameMap>(tag: K, options: ElementOptions = {},
  ...children: Child[]): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  fill(node, options, children);
  return node;
}

export function svg<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number> = {},
  ...children: Child[]): SVGElementTagNameMap[K] {
  const node = document.createElementNS(SVG_NS, tag);
  const text: Record<string, string> = {};
  for (const [name, value] of Object.entries(attrs)) text[name] = String(value);
  fill(node, { attrs: text }, children);
  return node;
}

/** Set text only when it changed (cheap at 20 Hz, avoids layout work). */
export function setText(node: Node, value: string): void {
  if (node.textContent !== value) node.textContent = value;
}

export function clear(node: Node): void {
  while (node.firstChild) node.removeChild(node.firstChild);
}

export function button(label: string, onClick: () => void, options: ElementOptions = {}): HTMLButtonElement {
  const node = el('button', { ...options, text: label, attrs: { type: 'button', ...(options.attrs ?? {}) } });
  node.addEventListener('click', onClick);
  return node;
}

/** Codicon-free inline mark for a state (no emoji: plain glyph in a span). */
export function stateDot(state: 'ok' | 'warn' | 'error' | 'idle'): HTMLSpanElement {
  return el('span', { className: `dot dot-${state}`, attrs: { 'aria-hidden': 'true' } });
}
