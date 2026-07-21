let state = {
  tasks: [],
  activeTaskId: null,
  currentPath: '',
  scanFiles: [],
  selectedFiles: [],
  pollingTimer: null,
  config: null,
};

async function api(url, body) {
  const opts = { headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) { opts.method = 'POST'; opts.body = JSON.stringify(body); }
  const res = await fetch(url, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

async function init() {
  state.config = await api('/api/config');
  await loadTasks();
  const activeTaskId = sessionStorage.getItem('activeTaskId');
  if (activeTaskId && state.tasks.some(t => t.id === activeTaskId)) {
    await selectTask(activeTaskId);
  } else if (state.tasks.length > 0) {
    const running = state.tasks.find(t => t.status === 'running' || t.status === 'cancelling');
    await selectTask(running ? running.id : state.tasks[0].id);
  } else {
    showNewTaskView();
  }
}

// ── Task list ──

async function loadTasks() {
  try {
    state.tasks = await api('/api/tasks');
    renderTaskList();
  } catch (e) {
    console.error('Failed to load tasks:', e);
  }
}

function renderTaskList() {
  const el = document.getElementById('taskList');
  el.innerHTML = '';

  if (!state.tasks.length) {
    el.innerHTML = '<div class="hint">暂无任务</div>';
    return;
  }

  state.tasks.forEach(t => {
    const div = document.createElement('div');
    div.className = 'task-item' + (t.id === state.activeTaskId ? ' task-active' : '');
    div.dataset.taskId = t.id;

    const statusIcon = { running: '▶', completed: '✓', cancelled: '✕', cancelling: '◼' }[t.status] || '?';
    const statusCls = 'task-badge task-badge-' + t.status;

    div.innerHTML =
      '<div class="task-item-inner" onclick="selectTask(\'' + t.id + '\')">' +
        '<span class="' + statusCls + '">' + statusIcon + '</span>' +
        '<span class="task-item-name">' + escapeHtml(t.display_path || t.name) + '</span>' +
        '<span class="task-item-progress">' +
          (t.status === 'running' || t.status === 'cancelling' ? t.progress + '%' : '') +
        '</span>' +
        '<span class="task-item-del" onclick="event.stopPropagation();deleteTask(\'' + t.id + '\')" title="删除任务">✕</span>' +
      '</div>';

    if (t.status === 'running' || t.status === 'cancelling') {
      const bar = document.createElement('div');
      bar.className = 'task-item-bar';
      bar.innerHTML = '<div class="task-item-bar-fill" style="width:' + t.progress + '%"></div>';
      div.appendChild(bar);
    }

    el.appendChild(div);
  });
}

async function selectTask(taskId) {
  if (state.pollingTimer) { clearInterval(state.pollingTimer); state.pollingTimer = null; }

  state.activeTaskId = taskId;
  sessionStorage.setItem('activeTaskId', taskId);
  renderTaskList();

  try {
    const status = await api('/api/status/' + taskId);
    showTaskDetailView(status);
    updateProgress(status);

    if (status.status === 'running' || status.status === 'cancelling') {
      document.getElementById('progressArea').style.display = 'block';
      state.pollingTimer = setInterval(() => pollStatus(taskId), 1000);
    } else {
      document.getElementById('progressArea').style.display = 'block';
      document.getElementById('btnCancel').disabled = true;
      document.getElementById('btnGenerate').disabled = true;
      document.getElementById('btnDownload').disabled = status.results.length === 0;
    }
  } catch (e) {
    showError('加载任务失败：' + e.message);
    showNewTaskView();
  }
}

async function newTask() {
  if (state.pollingTimer) { clearInterval(state.pollingTimer); state.pollingTimer = null; }
  state.activeTaskId = null;
  sessionStorage.removeItem('activeTaskId');
  renderTaskList();
  showNewTaskView();
}

// ── View switching ──

function showNewTaskView() {
  document.getElementById('newTaskArea').style.display = 'block';
  document.getElementById('taskDetailArea').style.display = 'none';
  document.getElementById('progressArea').style.display = 'none';
  document.getElementById('btnGenerate').disabled = true;
  document.getElementById('btnCancel').disabled = true;
  document.getElementById('btnDownload').disabled = true;

  if (!state.currentPath) {
    state.currentPath = state.config.base_path;
    browse(state.currentPath);
  }
}

function showTaskDetailView(status) {
  document.getElementById('newTaskArea').style.display = 'none';
  document.getElementById('taskDetailArea').style.display = 'block';
  document.getElementById('progressArea').style.display = 'block';

  document.getElementById('taskDetailPath').textContent = status.display_path || status.path || '/';

  const body = document.getElementById('taskDetailBody');
  body.innerHTML = '' +
    '<div class="detail-grid">' +
      '<div class="detail-item"><span class="detail-label">状态</span><span class="task-badge task-badge-' + status.status + '">' + statusText(status.status) + '</span></div>' +
      '<div class="detail-item"><span class="detail-label">进度</span><span>' + status.progress + '%</span></div>' +
      '<div class="detail-item"><span class="detail-label">完成</span><span>' + status.completed_files + ' / ' + status.total_files + '</span></div>' +
      (status.failed_files.length ? '<div class="detail-item"><span class="detail-label">失败</span><span class="failed-count">' + status.failed_files.length + ' 个</span></div>' : '') +
      '<div class="detail-item"><span class="detail-label">预览图</span><span>' + status.results.length + ' 张</span></div>' +
    '</div>';

  renderFileStatusList(status);

  if (status.status === 'running' || status.status === 'cancelling') {
    body.innerHTML += '<div class="btn-row" style="margin-top:12px"><button class="btn-danger" onclick="cancelTaskDetail(\'' + status.id + '\')">取消任务</button></div>';
  }
  if (status.status === 'completed' && status.results.length) {
    body.innerHTML += '<div class="btn-row" style="margin-top:12px"><button class="btn-success" onclick="downloadResults()">下载预览图 (ZIP)</button></div>';
  }
  if (status.status === 'completed' && status.failed_files && status.failed_files.length > 0) {
    body.innerHTML += '<div class="btn-row" style="margin-top:8px"><button class="btn-warning" onclick="retryFailed(\'' + status.id + '\')">重试失败 (' + status.failed_files.length + ' 个)</button></div>';
  }
  body.innerHTML += '<div class="btn-row" style="margin-top:12px;border-top:1px solid #eee;padding-top:12px"><button class="btn-danger" onclick="deleteTask(\'' + status.id + '\')" style="opacity:0.6">删除任务</button></div>';
}

async function cancelTaskDetail(taskId) {
  try { await api('/api/cancel/' + taskId, {}); } catch (e) { showError('取消失败：' + e.message); }
}

async function deleteTask(taskId) {
  if (!confirm('确定要删除此任务吗？\n生成的预览图文件不会被删除。')) return;
  try {
    if (state.pollingTimer && state.activeTaskId === taskId) {
      clearInterval(state.pollingTimer); state.pollingTimer = null;
    }
    await api('/api/tasks/' + taskId + '/delete', {});
    if (state.activeTaskId === taskId) {
      state.activeTaskId = null;
      sessionStorage.removeItem('activeTaskId');
    }
    await loadTasks();
    if (state.tasks.length > 0) {
      await selectTask(state.tasks[0].id);
    } else {
      showNewTaskView();
    }
  } catch (e) { showError('删除失败：' + e.message); }
}

async function cleanupTasks() {
  const hasFinished = state.tasks.some(t => t.status === 'completed' || t.status === 'cancelled');
  if (!hasFinished) return;
  if (!confirm('确定要清理所有已完成/已取消的任务吗？\n生成的预览图文件不会被删除。')) return;

  try {
    if (state.pollingTimer) { clearInterval(state.pollingTimer); state.pollingTimer = null; }
    const data = await api('/api/tasks/cleanup', {});
    state.activeTaskId = null;
    sessionStorage.removeItem('activeTaskId');
    await loadTasks();
    if (state.tasks.length > 0) {
      await selectTask(state.tasks[0].id);
    } else {
      showNewTaskView();
    }
  } catch (e) { showError('清理失败：' + e.message); }
}

function statusText(s) {
  return { running: '运行中', completed: '已完成', cancelled: '已取消', cancelling: '取消中' }[s] || s;
}

function renderFileStatusList(data) {
  const container = document.getElementById('fileStatusContainer');
  const fileStatuses = data.file_statuses || {};
  const fileErrors = data.file_errors || {};
  const entries = Object.entries(fileStatuses);

  if (!entries.length) {
    container.innerHTML = '';
    return;
  }

  const statusLabels = {
    'pending': '等待中',
    'processing': '处理中',
    'success': '成功',
    'failed': '失败'
  };
  const statusIcons = {
    'pending': '○',
    'processing': '▶',
    'success': '✓',
    'failed': '✕'
  };

  let html = '<div class="file-status-section"><div class="file-status-header">文件状态</div><div class="file-status-list">';

  for (const [filePath, status] of entries) {
    const fileName = filePath.split('/').pop();
    const error = fileErrors[filePath] || '';
    const label = statusLabels[status] || status;
    const icon = statusIcons[status] || '?';

    html += '<div class="file-status-item file-status-' + status + '"';
    if (error) {
      html += ' onclick="toggleFileError(this)" title="点击查看错误"';
    }
    html += '>';
    html += '<span class="file-status-icon">' + icon + '</span>';
    html += '<span class="file-status-name">' + escapeHtml(fileName) + '</span>';
    if (status === 'processing') {
      html += '<span class="file-status-label">' + label + ' <span class="processing-dot"></span></span>';
    } else {
      html += '<span class="file-status-label">' + label + '</span>';
    }
    if (error) {
      html += '<div class="file-status-error" style="display:none">' + escapeHtml(error) + '</div>';
    }
    html += '</div>';
  }

  html += '</div></div>';
  container.innerHTML = html;
}

function toggleFileError(el) {
  const err = el.querySelector('.file-status-error');
  if (err) {
    err.style.display = err.style.display === 'none' ? 'block' : 'none';
  }
}

async function retryFailed(taskId) {
  try {
    await api('/api/tasks/' + taskId + '/retry', {});
    await selectTask(taskId);
  } catch (e) {
    showError('重试失败：' + e.message);
  }
}

// ── Directory browsing (new task) ──

async function browse(path) {
  try {
    const data = await api('/api/browse', { path });
    state.currentPath = data.current_path;
    renderBrowser(data);
    document.getElementById('btnParent').disabled = !data.parent;
  } catch (e) { showError('浏览目录失败：' + e.message); }
}

function renderBrowser(data) {
  document.getElementById('displayPath').textContent = data.display_path;
  const el = document.getElementById('browser');
  el.innerHTML = '';
  data.directories.forEach(dir => {
    const div = document.createElement('div');
    div.className = 'browser-item browser-dir';
    div.innerHTML = '<span class="icon">📁</span><span class="name">' + escapeHtml(dir) + '</span>';
    div.onclick = () => browse(data.current_path + '/' + dir);
    el.appendChild(div);
  });
  data.video_files.forEach(f => {
    const div = document.createElement('div');
    div.className = 'browser-item';
    div.innerHTML = '<span class="icon">🎬</span><span class="name">' + escapeHtml(f) + '</span>';
    el.appendChild(div);
  });
  if (!data.directories.length && !data.video_files.length)
    el.innerHTML = '<div class="hint">（空目录）</div>';
}

async function refreshBrowse() { await browse(state.currentPath); }

async function goUp() {
  try {
    const data = await api('/api/browse', { path: state.currentPath });
    if (data.parent) await browse(data.parent);
  } catch (e) { showError('返回上级目录失败：' + e.message); }
}

async function scanDirectory() {
  const btn = document.getElementById('btnScan');
  btn.disabled = true; btn.textContent = '扫描中...';
  document.getElementById('fileList').innerHTML = '<div class="hint">扫描中，请稍候...</div>';
  try {
    const data = await api('/api/scan', { path: state.currentPath, files: [] });
    state.scanFiles = data.files;
    state.selectedFiles = data.files.slice();
    renderFileList(data.files);
    document.getElementById('fileCount').textContent = '已找到 ' + data.count + ' 个视频文件';
    document.getElementById('selectAll').checked = true;
    document.getElementById('selectAll').disabled = false;
    document.getElementById('btnGenerate').disabled = data.count === 0;
  } catch (e) {
    showError('扫描目录失败：' + e.message);
    document.getElementById('fileList').innerHTML = '<div class="hint">扫描失败</div>';
  } finally { btn.disabled = false; btn.textContent = '扫描视频'; }
}

function renderFileList(files) {
  const el = document.getElementById('fileList');
  el.innerHTML = '';
  if (!files.length) { el.innerHTML = '<div class="hint">未找到视频文件</div>'; return; }
  files.forEach((f, i) => {
    const name = f.replace(state.currentPath + '/', '');
    const div = document.createElement('div');
    div.className = 'file-item';
    div.innerHTML = '<input type="checkbox" checked data-index="' + i + '"><span class="name">' + escapeHtml(name) + '</span>';
    div.querySelector('input').onchange = updateSelection;
    el.appendChild(div);
  });
}

function updateSelection() {
  const checks = document.querySelectorAll('#fileList input[type="checkbox"]');
  state.selectedFiles = [];
  checks.forEach((cb, i) => { if (cb.checked) state.selectedFiles.push(state.scanFiles[i]); });
  const allChecked = checks.length > 0 && Array.from(checks).every(c => c.checked);
  document.getElementById('selectAll').checked = allChecked;
  document.getElementById('btnGenerate').disabled = state.selectedFiles.length === 0;
}

function toggleSelectAll() {
  const checked = document.getElementById('selectAll').checked;
  document.querySelectorAll('#fileList input[type="checkbox"]').forEach(cb => cb.checked = checked);
  updateSelection();
}

// ── Generate preview ──

async function startGeneration() {
  if (!state.selectedFiles.length) return;

  const cfg = {
    path: state.currentPath, files: state.selectedFiles,
    grid_cols: parseInt(document.getElementById('gridCols').value) || 6,
    grid_rows: parseInt(document.getElementById('gridRows').value) || 4,
    thumb_width: parseInt(document.getElementById('thumbWidth').value) || 320,
    thumb_height: parseInt(document.getElementById('thumbHeight').value) || 180,
    show_timestamps: document.getElementById('showTimestamps').checked,
  };

  try {
    const data = await api('/api/start', cfg);
    state.activeTaskId = data.task_id;
    sessionStorage.setItem('activeTaskId', data.task_id);
    await loadTasks();
    await selectTask(data.task_id);
  } catch (e) { showError('启动任务失败：' + e.message); }
}

async function pollStatus(taskId) {
  try {
    const data = await api('/api/status/' + taskId);
    updateProgress(data);

    if (data.status === 'completed' || data.status === 'cancelled') {
      clearInterval(state.pollingTimer); state.pollingTimer = null;
      document.getElementById('btnCancel').disabled = true;
      document.getElementById('btnGenerate').disabled = true;
      document.getElementById('btnDownload').disabled = data.results.length === 0;
      await loadTasks();
      await selectTask(taskId);
    }
    updateTaskItem(taskId, data);
  } catch (e) {
    clearInterval(state.pollingTimer); state.pollingTimer = null;
    showError('获取任务状态失败：' + e.message);
  }
}

function updateTaskItem(taskId, data) {
  const el = document.querySelector('.task-item[data-task-id="' + taskId + '"]');
  if (!el) return;
  const badge = el.querySelector('.task-badge');
  if (badge) { badge.className = 'task-badge task-badge-' + data.status; badge.textContent = { running: '▶', completed: '✓', cancelled: '✕', cancelling: '◼' }[data.status] || '?'; }
  const prog = el.querySelector('.task-item-progress');
  if (prog) prog.textContent = (data.status === 'running' || data.status === 'cancelling') ? data.progress + '%' : '';
  const bar = el.querySelector('.task-item-bar-fill');
  if (bar) bar.style.width = data.progress + '%';
}

function updateProgress(data) {
  document.getElementById('progressFill').style.width = data.progress + '%';
  document.getElementById('progressPercent').textContent = data.progress + '%';
  document.getElementById('completedCount').textContent = data.completed_files;
  document.getElementById('totalCount').textContent = data.total_files;

  if (data.current_file) {
    document.getElementById('currentFile').textContent = data.current_file.split('/').pop();
  } else {
    document.getElementById('currentFile').textContent = '';
  }

  const fd = document.getElementById('failedDisplay');
  fd.textContent = (data.failed_files && data.failed_files.length) ? '，失败 ' + data.failed_files.length + ' 个' : '';

  if (data.status === 'cancelled') document.getElementById('currentFile').textContent = '（已取消）';
  else if (data.status === 'completed') {
    const fc = data.failed_files ? data.failed_files.length : 0;
    document.getElementById('currentFile').textContent = fc ? '完成！成功 ' + data.completed_files + ' 个，失败 ' + fc + ' 个' : '✓ 完成！';
  }

  renderFileStatusList(data);
}

async function cancelGeneration() {
  if (!state.activeTaskId) return;
  try { await api('/api/cancel/' + state.activeTaskId, {}); } catch (e) { showError('取消失败：' + e.message); }
}

async function downloadResults() {
  if (!state.activeTaskId) return;
  try {
    const res = await fetch('/api/download/' + state.activeTaskId);
    if (!res.ok) { const err = await res.json().catch(() => ({ detail: res.statusText })); throw new Error(err.detail || '下载失败'); }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'previews_' + state.activeTaskId.slice(0, 8) + '.zip';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (e) { showError('下载失败：' + e.message); }
}

// ── Error ──

function showError(msg) {
  document.getElementById('errorCard').style.display = 'block';
  const el = document.getElementById('errorList');
  const div = document.createElement('div');
  div.textContent = '[' + new Date().toLocaleTimeString() + '] ' + msg;
  el.appendChild(div);
}

function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str; return d.innerHTML;
}

init();
