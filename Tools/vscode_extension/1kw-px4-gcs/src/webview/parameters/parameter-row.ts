// One parameter row: name, value, build default, units and the "differs from
// build default" mark, all as text nodes. A click opens the editor.
import { ParamEntry } from '../../dashboard/dashboard-messages';
import { el } from '../dom-helpers';
import { formatParamValue } from '../format/telemetry-format';

export function parameterRow(param: ParamEntry, top: number, height: number, onOpen: (name: string) => void): HTMLElement {
  const meta = param.meta;
  const row = el('div', {
    className: `param-row${param.differs ? ' differs' : ''}`,
    attrs: { role: 'row', tabindex: '0', 'aria-label': `${param.name}, edit` },
    title: meta?.shortDesc,
  },
  el('span', { className: 'param-name', text: param.name, attrs: { role: 'cell' } }),
  el('span', { className: 'param-value', text: formatParamValue(param.value, param.type), attrs: { role: 'cell' } }),
  el('span', { className: 'param-default', text: meta?.default !== undefined ? formatParamValue(meta.default, param.type) : '',
    attrs: { role: 'cell' } }),
  el('span', { className: 'param-units', text: meta?.units ?? '', attrs: { role: 'cell' } }),
  el('span', { className: 'param-differs', text: param.differs ? '≠' : '', attrs: { role: 'cell' } }));
  row.style.top = `${top}px`;
  row.style.height = `${height}px`;
  row.addEventListener('click', () => onOpen(param.name));
  row.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onOpen(param.name);
    }
  });
  return row;
}
