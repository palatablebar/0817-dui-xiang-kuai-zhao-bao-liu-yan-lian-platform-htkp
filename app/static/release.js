import {element} from './client.js';

const reasons = {
  RECLAIM: '可回收',
  LIVE_SNAPSHOT: '活动快照',
  LEGAL_HOLD: '合法保全',
  RETENTION: '保留期',
  UNRESOLVED: '待对平',
};
const columns = ['对象', '业务分组', '记录键', '容量', '处置', '依据'];

function basisText(entry) {
  const basis = entry.basis || {};
  if (entry.reason === 'LIVE_SNAPSHOT') {
    return `快照 ${basis.snapshot_ids?.join(',') ?? '—'} · 引用 ${basis.references?.join(',') ?? '—'}`;
  }
  if (entry.reason === 'LEGAL_HOLD') return `保全标记 ${basis.policy ?? '—'}`;
  if (entry.reason === 'RETENTION') {
    return `入库 ${basis.entry_day} · 当前 ${basis.current_day} · 保留 ${basis.retention_days} 天`;
  }
  if (entry.reason === 'UNRESOLVED') {
    return `${basis.group_status ?? '—'} · 计算依据 ${basis.calculated ?? '—'}`;
  }
  return `入库 ${basis.entry_day} · 当前 ${basis.current_day} · 保留 ${basis.retention_days} 天`;
}

function optionButton(option) {
  const button = element('button', undefined, {
    type: 'button',
    'data-decision': option.status,
    'aria-pressed': 'false',
  });
  button.disabled = !option.available;
  button.append(
    element('span', option.label),
    element(
      'small',
      option.available
        ? option.status === 'HELD'
          ? '先不释放，保留整批待齐'
          : `释放 ${option.bytes} 字节`
        : `不可用 · ${option.blockers.join('、') || '条件不足'}`,
    ),
  );
  return button;
}

export function release(report, decide) {
  const target = report.release;
  if (!target) return;
  document.querySelector('#release-summary').textContent = target.summary;
  document.querySelector('[data-release="bytes"]').textContent = target.capacity.bytes;
  document.querySelector('[data-release="objects"]').textContent = target.capacity.objects;
  document.querySelector('[data-release="retained"]').textContent = target.retained.length;

  const note = document.querySelector('#release-note');
  note.dataset.blocked = String(target.blocked);
  note.textContent = target.blocked
    ? '对账任一不一致，执行已挡住；请先处理下表标记的差异。'
    : `潜在可回收 ${target.potential.bytes} 字节，其中已确认安全 ${target.capacity.bytes} 字节；` +
      `${target.retained.length} 个对象因快照、保全、保留期或未对平而留存。`;

  const table = document.querySelector('#release-rows');
  table.replaceChildren();
  const head = element('tr');
  head.append(...columns.map(title => element('th', title, {scope: 'col'})));
  const body = table.createTBody();
  for (const entry of [...target.reclaimable, ...target.retained]) {
    const tr = body.insertRow();
    const kind = element('td', reasons[entry.reason] || entry.reason, {'data-kind': entry.reason});
    const origin = entry.line ? `${entry.record} · 第 ${entry.line} 行` : entry.record;
    tr.append(
      element('td', entry.object_id),
      element('td', entry.case),
      element('td', origin),
      element('td', entry.size_bytes),
      kind,
      element('td', `${basisText(entry)} · ${entry.basis?.detail ?? ''}`, {class: 'basis'}),
    );
  }
  if (!target.reclaimable.length && !target.retained.length) {
    body.insertRow().insertCell().textContent = '当前没有对象行';
  }
  table.createTHead().append(head);

  const options = document.querySelector('#release-options');
  options.replaceChildren();
  for (const option of target.options) {
    const button = optionButton(option);
    button.addEventListener('click', () => decide(option.status));
    options.append(button);
  }

  const checks = document.querySelector('#release-checks');
  checks.replaceChildren();
  for (const check of target.reconciliation.checks) {
    const item = element(
      'li',
      check.expected === undefined
        ? `${check.label} ${check.ok ? '一致' : '不一致'}`
        : `${check.label} ${check.actual}/${check.expected}${check.ok ? '' : ' 不一致'}`,
      {'data-ok': String(check.ok)},
    );
    checks.append(item);
  }
  if (target.blocked) {
    checks.append(
      element('li', `已挡住执行：${target.reconciliation.blockers.join('、')}`, {'data-ok': 'false'}),
    );
  }

  document.querySelector('#release-quarantine').textContent = target.quarantined.length
    ? `隔离行 ${target.quarantined.length} 条：` +
      target.quarantined.map(row => `第 ${row.line} 行 ${row.record}（${row.reason}）`).join('；')
    : '隔离行 0 条';
}
