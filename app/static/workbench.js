import {request} from './client.js';
import {snapshot, history} from './view.js';
import {visualize} from './plots.js';
import {release} from './release.js';

const form = document.querySelector('#source');
const file = document.querySelector('#file');
const profile = document.querySelector('#profile');
const status = document.querySelector('#notice');
const detail = document.querySelector('#review');
const evidence = document.querySelector('#evidence');
const stages = [...document.querySelectorAll('[data-stage]')];
let stage = 'balance';
let report, selected, batch, running = false;
let decision = null;

function source() {
  const data = new FormData();
  if (file.files.length) data.append('file',file.files[0]);
  else data.append('sample',profile.value);
  return data;
}

function announce(text, failure = false) {
  status.textContent = text;
  status.dataset.failure = String(failure);
}

function choose(kind) {
  decision = kind;
  for (const button of document.querySelectorAll('[data-decision]')) {
    const active = button.dataset.decision === kind;
    button.setAttribute('aria-pressed', String(active));
  }
  const option = report?.release?.options?.find(item => item.status === kind);
  if (!option) return;
  if (!batch) {
    announce(`${option.label} · 先执行批次，再在复核意见中提交`);
    return;
  }
  if (!detail.querySelector(`[value="${kind}"]`).disabled) {
    detail.elements.note.focus();
    announce(`${option.label} · 在复核意见中说明后提交`);
  } else {
    announce(`${option.label} 当前不可用`, true);
  }
}

function draw() {
  if (!report) return;
  snapshot(report, selected, stage);
  visualize(report, selected);
  const panel = document.querySelector('#release-panel');
  panel.hidden = !report.release;
  if (report.release) {
    release(report, choose);
    for (const button of document.querySelectorAll('[data-decision]')) {
      button.setAttribute('aria-pressed', String(button.dataset.decision === decision));
    }
  }
  for (const button of stages) button.setAttribute('aria-pressed',String(button.dataset.stage===stage));
  document.querySelector('#panel-title').textContent = stages.find(button => button.dataset.stage===stage)?.textContent || '运行对账';
  detail.hidden = !batch;
  if (batch) {
    document.querySelector('#run-status').textContent = `${batch.id.slice(0,10)} · ${batch.status} · r${batch.revision}`;
    const options = report.release?.options || [];
    const available = kind => batch.status !== 'APPROVED' && batch.status !== 'PARTIAL' &&
      Boolean(options.find(item => item.status===kind)?.available);
    detail.querySelector('[value="APPROVED"]').disabled = !available('APPROVED');
    detail.querySelector('[value="PARTIAL"]').disabled = !available('PARTIAL');
    detail.querySelector('[value="HELD"]').disabled = batch.status==='APPROVED' || batch.status==='PARTIAL';
    evidence.href = `/api/runs/${batch.id}/evidence`;
  }
}

function show(payload, committed = false) {
  batch = committed ? payload : null;
  report = committed ? payload.report : payload;
  detail.elements.note.value = batch?.note || '';
  selected = report.cases?.[0]?.case;
  decision = null;
  draw();
}

async function refresh() {
  const data = await request('/api/runs');
  history(data.items, batch?.id);
}

async function perform(action) {
  if (running) return;
  running = true;
  document.body.setAttribute('aria-busy','true');
  announce('处理中…');
  try { await action(); }
  catch (error) { announce(error.message,true); }
  finally { running = false; document.body.removeAttribute('aria-busy'); }
}

function preview(next) {
  return perform(async () => {
    const payload = await request(`/api/stages/${next}`,{method:'POST',body:source()});
    stage = next;
    show(payload);
    announce('阶段预览已更新');
    await refresh();
  });
}

stages.forEach(button => button.addEventListener('click',()=>preview(button.dataset.stage)));
form.addEventListener('submit', event => {
  event.preventDefault();
  perform(async () => {
    const result = await request('/api/runs',{method:'POST',body:source()});
    stage = 'balance'; show(result,true);
    announce('批次已保存'); await refresh();
  });
});
const filename = document.querySelector('#file-name');
profile.addEventListener('change',()=>{file.value=''; filename.textContent=''; preview(stage);});
file.addEventListener('change',()=>{filename.textContent=file.files[0]?.name || ''; preview(stage);});
document.querySelector('#rows').addEventListener('click',event=>{
  const button = event.target.closest('[data-case]');
  if (button) { selected = button.dataset.case; draw(); document.querySelector(`[data-case="${CSS.escape(selected)}"]`).focus(); }
});
document.querySelector('#history').addEventListener('click',event=>{
  const button = event.target.closest('[data-run]');
  if (button) perform(async()=>{
    const result = await request(`/api/runs/${button.dataset.run}`);
    stage='balance'; show(result,true); announce('已载入历史批次'); await refresh();
  });
});
detail.addEventListener('submit',event=>{
  event.preventDefault();
  perform(async()=>{
    const payload={status:event.submitter.value,revision:batch.revision,note:detail.elements.note.value};
    const result=await request(`/api/runs/${batch.id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const done={APPROVED:'批次已整批签发',PARTIAL:'已先释放确认安全的对象',HELD:'批次已暂缓'};
    show(result,true); announce(done[result.status] || '复核已记录'); await refresh();
  });
});
preview(stage);
