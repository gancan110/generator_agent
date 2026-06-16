// ─── Config ──────────────────────────────────────────────────────
const API = {
  projects: '/api/projects',
  chapter: (p) => `/api/chapter?path=${encodeURIComponent(p)}`,
  wizardCreate: '/api/wizard/create',
  wizardGet: (s) => `/api/wizard/${s}`,
  wizardSteps: (s) => `/api/wizard/${s}/steps`,
  wizardPrompt: (s, step) => `/api/wizard/${s}/prompt/${step}`,
  wizardSave: (s) => `/api/wizard/${s}/save`,
  wizardGenerate: (s, step) => `/api/wizard/${s}/generate/${step}`,
  wizardConfirm: (s) => `/api/wizard/${s}/confirm`,
  wizardStartGen: (s) => `/api/wizard/${s}/start-generation`,
};

// ─── State ──────────────────────────────────────────────────────
const state = {
  sessionId: null,
  steps: [],
  currentStep: null,
  currentStepIdx: 0,
  projectId: null,
  isGenerating: false,
  isStreaming: false,
  readerProject: null,
  readerChapterIdx: 0,
};

// ─── DOM refs ───────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const el = {};

function initEls() {
  const ids = [
    'startWizardBtn', 'projectListView',
    'welcome', 'stepView', 'genView', 'readerView',
    'stepProgress', 'stepTitle', 'stepDesc', 'stepBody', 'stepActions',
    'stepBackBtn', 'stepGenerateBtn', 'stepRegenBtn', 'stepConfirmBtn',
    'genStatus', 'genProgressFill', 'genProgressLabel', 'genProgressCount',
    'genLogViewer', 'genChapterPreview', 'genChapterBadge',
    'readerProjectName', 'readerChapterNum', 'readerPrevBtn', 'readerNextBtn',
    'readerBackBtn', 'readerChapterTitle', 'readerChapterContent',
    'systemLog', 'clearLogBtn',
    'outlineSidebar', 'outlineSidebarContent', 'closeOutlineSidebar',
  ];
  for (const id of ids) el[id] = $(id);
}

// ─── Utilities ──────────────────────────────────────────────────
async function api(url, opts = {}, retries = 3) {
  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(url, opts);
      
      // 处理速率限制
      if (res.status === 429) {
        const delay = 1000 * (i + 1);
        log(`请求过于频繁，${delay}ms后重试...`, 'warn');
        await new Promise(r => setTimeout(r, delay));
        continue;
      }
      
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: res.statusText }));
        throw new Error(err.error || `HTTP ${res.status}`);
      }
      
      const ct = res.headers.get('content-type') || '';
      if (ct.includes('text/event-stream')) return res;
      return res.json();
    } catch (e) {
      if (i === retries - 1) throw e;
      const delay = 500 * (i + 1);
      log(`请求失败，${delay}ms后重试...`, 'warn');
      await new Promise(r => setTimeout(r, delay));
    }
  }
}

// 全局错误处理
window.onerror = function(msg, url, line, col, error) {
  log(`JavaScript错误: ${msg} (${url}:${line}:${col})`, 'error');
  return false;
};

window.addEventListener('unhandledrejection', function(e) {
  log(`未处理的Promise错误: ${e.reason?.message || e.reason}`, 'error');
});

// XSS防护：转义HTML特殊字符
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// 创建安全的DOM元素
function safeCreateElement(tag, attrs = {}, children = []) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === 'className') {
      el.className = value;
    } else if (key === 'textContent') {
      el.textContent = value;
    } else if (key === 'innerHTML') {
      // 仅允许静态HTML，不接受用户输入
      el.innerHTML = value;
    } else if (key.startsWith('on')) {
      el[key] = value;
    } else {
      el.setAttribute(key, value);
    }
  }
  for (const child of children) {
    if (typeof child === 'string') {
      el.appendChild(document.createTextNode(child));
    } else if (child instanceof Node) {
      el.appendChild(child);
    }
  }
  return el;
}

function log(text, cls = '') {
  const e = document.createElement('div');
  e.className = 'log-entry ' + cls;
  e.textContent = text;
  el.systemLog.appendChild(e);
  el.systemLog.scrollTop = el.systemLog.scrollHeight;
}

function showView(name) {
  ['welcome', 'stepView', 'genView', 'readerView'].forEach(v => {
    el[v].classList.toggle('active', v === name);
  });
}

// ─── Outline Sidebar ─────────────────────────────────────────────
async function showOutlineSidebar(sessId, currentStep) {
  try {
    const resp = await fetch(`/api/wizard/${sessId}/outline-data`);
    const data = await resp.json();
    if (!data.outline) {
      el.outlineSidebar.style.display = 'none';
      document.body.classList.remove('sidebar-open');
      return;
    }
    
    const outline = data.outline;
    const currentChapter = data.current_chapter || 1;
    const totalChapters = data.total_chapters || 10;
    const completedChapters = data.completed_chapters || [];
    
    // Parse outline into chapters
    const chapters = parseOutlineChapters(outline);
    
    let html = '';
    
    // Overall summary
    html += `<div style="margin-bottom:12px;padding:8px 12px;background:var(--bg3);border-radius:6px;">
      <div style="font-weight:bold;color:var(--accent);margin-bottom:4px;">📊 进度：第${currentChapter}/${totalChapters}章</div>
      <div style="font-size:12px;color:var(--text2);">已完成 ${completedChapters.length} 章</div>
    </div>`;
    
    // Chapter list
    if (chapters.length > 0) {
      for (const ch of chapters) {
        const isActive = ch.num === currentChapter;
        const isDone = completedChapters.includes(ch.num);
        const statusIcon = isDone ? '✅' : (isActive ? '▶️' : '⏳');
        html += `<div class="outline-chapter-item${isActive ? ' active' : ''}">
          <div><span class="ch-num">${statusIcon} 第${ch.num}章</span><span class="ch-title">${escapeHtml(ch.title)}</span></div>
          ${ch.events ? `<div class="ch-events">${escapeHtml(ch.events)}</div>` : ''}
        </div>`;
      }
    } else {
      // Fallback: show raw outline with markdown
      html += `<div style="font-size:13px;line-height:1.7;">${renderMarkdown(outline)}</div>`;
    }
    
    el.outlineSidebarContent.innerHTML = html;
    el.outlineSidebar.style.display = 'flex';
    document.body.classList.add('sidebar-open');
    
    // Close button
    el.closeOutlineSidebar.onclick = () => {
      el.outlineSidebar.style.display = 'none';
      document.body.classList.remove('sidebar-open');
    };
  } catch (e) {
    console.error('Failed to load outline sidebar:', e);
    el.outlineSidebar.style.display = 'none';
    document.body.classList.remove('sidebar-open');
  }
}

function hideOutlineSidebar() {
  el.outlineSidebar.style.display = 'none';
  document.body.classList.remove('sidebar-open');
}

function parseOutlineChapters(outlineText) {
  const chapters = [];
  if (!outlineText) return chapters;
  
  // Match patterns like "第1章", "1.", "1、", "Chapter 1", etc.
  const lines = outlineText.split('\n');
  let current = null;
  
  for (const line of lines) {
    const trimmed = line.trim();
    // Match chapter headers
    const m = trimmed.match(/^(?:第(\d+)章|(\d+)[.、）\)]|Chapter\s*(\d+))[：:\s]*(.*)/i);
    if (m) {
      if (current) chapters.push(current);
      const num = parseInt(m[1] || m[2] || m[3]);
      const title = (m[4] || '').trim();
      current = { num, title: title || `第${num}章`, events: '' };
    } else if (current && trimmed && !trimmed.startsWith('#')) {
      // Accumulate events/details for this chapter
      if (trimmed.startsWith('-') || trimmed.startsWith('·') || trimmed.startsWith('*')) {
        current.events += trimmed.replace(/^[-·*]\s*/, '') + '；';
      } else if (!current.events) {
        current.events = trimmed.substring(0, 80);
      }
    }
  }
  if (current) chapters.push(current);
  
  // Limit events length
  for (const ch of chapters) {
    if (ch.events.length > 100) ch.events = ch.events.substring(0, 97) + '...';
  }
  
  return chapters;
}

// ─── Step Progress Bar ──────────────────────────────────────────
function renderStepProgress() {
  el.stepProgress.innerHTML = '';
  const labels = {
    title_input: '小说标题',
    genre_input: '题材分析',
    writing_style: '写作风格',
    worldview: '世界观',
    skill: '写作风格指南',
    import_novel: '导入小说',
    project_init: '项目初始化',
    outline: '大纲生成',
    chapter_config: '章节设置',
    chapter_gen: '章节生成',
    chapter_review: '章节审核',
    chapter_update: '更新数据库',
  };
  for (const s of state.steps) {
    const dot = document.createElement('div');
    dot.className = 'step-dot';
    if (s.confirmed) dot.classList.add('done');
    if (s.current) dot.classList.add('active');
    const icon = s.confirmed ? '✓' : s.current ? '●' : '○';
    
    // 使用textContent安全地设置内容
    const iconSpan = document.createElement('span');
    iconSpan.className = 'dot-icon';
    iconSpan.textContent = icon;
    dot.appendChild(iconSpan);
    dot.appendChild(document.createTextNode(' ' + (labels[s.name] || s.name)));
    
    dot.title = labels[s.name] || s.name;
    el.stepProgress.appendChild(dot);
  }
}

// ─── Welcome & Projects ─────────────────────────────────────────
async function loadProjects() {
  try {
    const list = await api(API.projects);
    el.projectListView.innerHTML = '';
    if (!list.length) { el.projectListView.innerHTML = '<div style="color:var(--text3);font-size:13px">暂无项目</div>'; return; }
      for (const p of list.slice().reverse().slice(0, 10)) {
        const item = document.createElement('div');
        item.className = 'proj-item';
        const statusMap = { completed: '已完成', running: '生成中', error: '失败', unknown: '—' };
        
        // 使用textContent安全地设置内容
        const nameSpan = document.createElement('span');
        nameSpan.className = 'proj-name';
        nameSpan.textContent = p.name;
        
        const metaSpan = document.createElement('span');
        metaSpan.className = 'proj-meta';
        metaSpan.textContent = `${p.chapter_count}章 · ${statusMap[p.status]||p.status}`;
        
        item.appendChild(nameSpan);
        item.appendChild(metaSpan);
        item.addEventListener('click', () => openReader(p));
        el.projectListView.appendChild(item);
      }
  } catch (e) { console.error(e); }
}

// ─── Wizard Init ────────────────────────────────────────────────
async function startWizard() {
  const sess = await api(API.wizardCreate, { method: 'POST' });
  state.sessionId = sess.session_id;
  state.steps = (await api(API.wizardSteps(sess.session_id))).steps;
  state.currentStep = sess.step;
  state.currentStepIdx = sess.step_idx;
  renderStepProgress();
  showView('stepView');
  await loadStep(sess.step);
}

// ─── Load Step ─────────────────────────────────────────────────
async function loadStep(step) {
  const sessId = state.sessionId;
  if (!sessId) return;

  el.stepGenerateBtn.style.display = 'none';
  el.stepRegenBtn.style.display = 'none';
  el.stepConfirmBtn.style.display = 'none';
  el.stepBackBtn.style.display = state.currentStepIdx > 0 ? 'inline-block' : 'none';

  // Show/hide outline sidebar for chapter_gen step
  if (step === 'chapter_gen' || step === 'chapter_review') {
    showOutlineSidebar(sessId, step);
  } else {
    hideOutlineSidebar();
  }

  const labels = {
    title_input: '第一步：输入小说标题',
    genre_input: '第二步：输入题材并分析',
    writing_style: '第三步：制定写作风格',
    worldview: '第四步：生成世界观',
    skill: '第五步：生成写作风格指南',
    import_novel: '第六步：导入已有小说',
    project_init: '第七步：初始化项目',
    outline: '第八步：生成大纲',
    chapter_config: '第九步：设置章节参数',
    chapter_gen: '第十步：生成章节内容',
    chapter_review: '第十一步：章节审核',
    chapter_update: '第十二步：更新数据库',
  };
  el.stepTitle.textContent = labels[step] || step;

  const promptData = await api(API.wizardPrompt(sessId, step));
  el.stepBody.innerHTML = '';
  el.stepDesc.textContent = promptData.description || '';

  if (promptData.type === 'form') {
    renderFormStep(step, promptData);
  } else if (promptData.type === 'model') {
    await renderModelStep(step, promptData);
  } else if (promptData.type === 'action') {
    renderActionStep(step, promptData);
  }
}

// ─── Form Step ─────────────────────────────────────────────────
function renderFormStep(step, data) {
  const form = document.createElement('div');
  form.className = 'form-fields';
  for (const f of (data.fields || [])) {
    const g = document.createElement('div');
    g.className = 'form-group';
    g.innerHTML = `<label>${f.label}</label>`;
    if (f.type === 'number') {
      g.innerHTML += `<input type="number" id="ff_${f.name}" value="${f.value||''}" min="${f.min||1}" max="${f.max||200}">`;
    } else if (f.type === 'textarea') {
      g.innerHTML += `<textarea id="ff_${f.name}" placeholder="${f.placeholder||''}" rows="6">${f.value||''}</textarea>`;
    } else if (f.type === 'select') {
      let optionsHtml = '';
      for (const opt of (f.options || [])) {
        const selected = opt.value === (f.value || '') ? 'selected' : '';
        optionsHtml += `<option value="${opt.value}" ${selected}>${opt.label}</option>`;
      }
      g.innerHTML += `<select id="ff_${f.name}">${optionsHtml}</select>`;
    } else {
      g.innerHTML += `<input type="text" id="ff_${f.name}" placeholder="${f.placeholder||''}" ${f.required?'required':''} value="${f.value||''}">`;
    }
    form.appendChild(g);
  }
  el.stepBody.appendChild(form);
  el.stepConfirmBtn.style.display = 'inline-block';
  el.stepConfirmBtn.textContent = '确认并继续';
  el.stepConfirmBtn.onclick = async () => {
    const data = {};
    for (const f of (el.stepBody.querySelectorAll('[id^="ff_"]'))) {
      data[f.id.replace('ff_', '')] = f.value;
    }
    await api(API.wizardSave(state.sessionId), {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ step, data }),
    });
    await confirmStep(step, data);
  };
}

// ─── Action Step ───────────────────────────────────────────────
function renderActionStep(step, data) {
  const actionDiv = document.createElement('div');
  actionDiv.className = 'action-step';
  actionDiv.innerHTML = `
    <div class="action-info">
      <div class="action-icon">⚡</div>
      <p>${data.description}</p>
    </div>
  `;
  el.stepBody.appendChild(actionDiv);
  
  el.stepConfirmBtn.style.display = 'inline-block';
  el.stepConfirmBtn.textContent = '执行操作';
  el.stepConfirmBtn.onclick = async () => {
    el.stepConfirmBtn.disabled = true;
    el.stepConfirmBtn.textContent = '执行中...';
    
    // Simulate action execution
    setTimeout(async () => {
      await confirmStep(step, {});
      el.stepConfirmBtn.disabled = false;
    }, 1000);
  };
}

// ─── Model Step ─────────────────────────────────────────────────
async function renderModelStep(step, data) {
  // Dynamic fields based on step
  if (data.fields) {
    for (const field of data.fields) {
      const fieldDiv = document.createElement('div');
      fieldDiv.className = 'chapter-count-input';
      
      let inputHtml = '';
      if (field.type === 'text' || !field.type) {
        inputHtml = `<input type="text" id="field_${field.name}" placeholder="${field.placeholder || ''}" value="${field.value || ''}" ${field.required ? 'required' : ''}>`;
      } else if (field.type === 'textarea') {
        inputHtml = `<textarea id="field_${field.name}" placeholder="${field.placeholder || ''}" rows="4">${field.value || ''}</textarea>`;
      } else if (field.type === 'select') {
        let optionsHtml = '';
        for (const opt of (field.options || [])) {
          const selected = opt.value === (field.value || '') ? 'selected' : '';
          optionsHtml += `<option value="${opt.value}" ${selected}>${opt.label}</option>`;
        }
        inputHtml = `<select id="field_${field.name}">${optionsHtml}</select>`;
      } else {
        inputHtml = `<input type="number" id="field_${field.name}" value="${field.value || 10}" min="${field.min || 1}" max="${field.max || 100}">`;
      }
      
      fieldDiv.innerHTML = `<label>${field.label}：</label>${inputHtml}`;
      el.stepBody.appendChild(fieldDiv);
    }
  }

  // Prompt editor (collapsible)
  const pe = document.createElement('div');
  pe.className = 'prompt-editor collapsed';
  pe.innerHTML = `
    <div class="prompt-header">
      <label><input type="checkbox" class="toggle-prompt"> 编辑 Prompt</label>
      <span style="font-size:11px;color:var(--text3)">展开可编辑发送给模型的指令</span>
    </div>
    <textarea id="systemPromptEdit" style="display:none">${escapeHtml(data.system_prompt || '')}</textarea>
    <textarea id="userPromptEdit">${escapeHtml(data.user_prompt || '')}</textarea>
  `;
  el.stepBody.appendChild(pe);

  // Toggle prompt visibility
  pe.querySelector('.toggle-prompt').addEventListener('change', function() {
    pe.classList.toggle('collapsed', !this.checked);
    pe.querySelector('#systemPromptEdit').style.display = this.checked ? 'block' : 'none';
  });

  // Stream output area
  const so = document.createElement('div');
  so.className = 'stream-output';
  so.id = 'streamOutput';
  so.innerHTML = '<div class="placeholder">点击「生成」按钮调用模型...</div>';
  el.stepBody.appendChild(so);

  // Result editor (hidden initially)
  const re = document.createElement('div');
  re.className = 'result-editor';
  re.id = 'resultEditor';
  re.innerHTML = `
    <textarea id="resultEditText"></textarea>
    <div class="editor-actions">
      <button class="btn" id="cancelEditBtn">取消</button>
      <button class="btn-primary" id="saveEditBtn">保存修改</button>
    </div>
  `;
  el.stepBody.appendChild(re);

  // Save prompt edits
  async function savePromptEdits() {
    const sysP = document.getElementById('systemPromptEdit')?.value || '';
    let userP = document.getElementById('userPromptEdit')?.value || '';
    const saveData = { system_prompt: sysP, user_prompt: userP, temperature: data.temperature || 0.7 };
    
    // Add field values if they exist
    for (const field of (data.fields || [])) {
      const fieldInput = document.getElementById(`field_${field.name}`);
      if (fieldInput) {
        saveData[field.name] = fieldInput.value;
        
        // Update user_prompt with field value if it contains the placeholder
        if (step === 'genre_input' && field.name === 'genre') {
          const genreValue = fieldInput.value;
          if (genreValue) {
            userP = userP.replace(/题材：.*/m, `题材：${genreValue}`);
            saveData.user_prompt = userP;
          }
        }
        if (step === 'outline' && field.name === 'chapter_count') {
          const cc = fieldInput.value;
          if (cc) {
            userP = userP.replace(/共\d+章/, `共${cc}章`);
            saveData.user_prompt = userP;
          }
        }
        if (step === 'chapter_gen') {
          if (field.name === 'chapter_number') {
            const cn = fieldInput.value;
            if (cn) {
              userP = userP.replace(/第\d+章/, `第${cn}章`);
              saveData.user_prompt = userP;
            }
          }
          if (field.name === 'target_words') {
            const tw = fieldInput.value;
            if (tw) {
              userP = userP.replace(/约\d+字/, `约${tw}字`);
              saveData.user_prompt = userP;
            }
          }
        }
      }
    }
    
    await api(API.wizardSave(state.sessionId), {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ step, data: saveData }),
    });
    
    // Reload prompt from server to reflect custom_ideas changes
    if (saveData.custom_ideas !== undefined) {
      const refreshed = await api(API.wizardPrompt(state.sessionId, step));
      const sysEdit = document.getElementById('systemPromptEdit');
      const userEdit = document.getElementById('userPromptEdit');
      if (sysEdit && refreshed.system_prompt) sysEdit.value = refreshed.system_prompt;
      if (userEdit && refreshed.user_prompt) userEdit.value = refreshed.user_prompt;
    }
  }

  // Generate button
  el.stepGenerateBtn.style.display = 'inline-block';
  el.stepGenerateBtn.textContent = '🚀 生成';
  el.stepGenerateBtn.onclick = async () => {
    await savePromptEdits();
    await streamGenerate(step);
  };

  // Regenerate button (hidden until first generation)
  el.stepRegenBtn.style.display = 'none';
  el.stepRegenBtn.textContent = '🔄 重新生成';
  el.stepRegenBtn.onclick = async () => {
    await savePromptEdits();
    await streamGenerate(step);
  };

  // Confirm button (hidden until generation done)
  el.stepConfirmBtn.style.display = 'none';
  el.stepConfirmBtn.textContent = '✓ 确认并继续';
  el.stepConfirmBtn.onclick = async () => {
    // Save edited result + field values
    const finalResult = document.getElementById('resultEditText')?.value || document.getElementById('streamOutput')?.textContent || '';
    const confirmData = { result: finalResult };
    for (const field of (data.fields || [])) {
      const fieldInput = document.getElementById(`field_${field.name}`);
      if (fieldInput) confirmData[field.name] = fieldInput.value;
    }
    const resp = await api(API.wizardConfirm(state.sessionId), {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ step, data: confirmData }),
    });
    // Refresh steps
    state.steps = (await api(API.wizardSteps(state.sessionId))).steps;
    renderStepProgress();
    
    if (resp.loop_back) {
      // Review failed or next chapter - reload same step
      if (resp.review) {
        showReviewFeedback(step, resp.review);
      }
      state.currentStep = resp.next_step;
      state.currentStepIdx = resp.next_step_idx;
      await loadStep(resp.next_step);
      renderStepProgress();
    } else {
      // Advance to next step
      state.currentStep = resp.next_step;
      state.currentStepIdx = resp.next_step_idx;
      await loadStep(resp.next_step);
      renderStepProgress();
    }
  };
}

// ─── Stream Generate ────────────────────────────────────────────
async function streamGenerate(step) {
  if (state.isStreaming) return;
  state.isStreaming = true;
  el.stepGenerateBtn.style.display = 'none';
  el.stepRegenBtn.style.display = 'none';
  el.stepConfirmBtn.style.display = 'none';

  const so = document.getElementById('streamOutput');
  so.innerHTML = '';
  let fullText = '';

  try {
    const res = await api(API.wizardGenerate(state.sessionId, step));
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const msg = JSON.parse(line.slice(6));
          if (msg.type === 'chunk') {
            fullText += msg.text;
            renderStreamBlocks(so, fullText);
          } else if (msg.type === 'done') {
            fullText = msg.text || fullText;
            renderStreamBlocks(so, fullText);
            onGenerationDone(step, fullText);
          } else if (msg.type === 'error') {
            so.innerHTML = '';
            const errorDiv = document.createElement('div');
            errorDiv.className = 'placeholder';
            errorDiv.style.color = 'var(--accent)';
            errorDiv.textContent = '错误: ' + msg.text;
            so.appendChild(errorDiv);
            state.isStreaming = false;
            el.stepGenerateBtn.style.display = 'inline-block';
          }
        } catch (e) { /* ignore parse errors */ }
      }
    }
  } catch (e) {
    so.innerHTML = '';
    const errorDiv = document.createElement('div');
    errorDiv.className = 'placeholder';
    errorDiv.style.color = 'var(--accent)';
    errorDiv.textContent = '请求失败: ' + e.message;
    so.appendChild(errorDiv);
  }
  state.isStreaming = false;
}

// ─── Block-level Typewriter ─────────────────────────────────────
function renderStreamBlocks(container, text) {
  // 按段落分割（双换行）
  const blocks = text.split(/\n{2,}/).filter(b => b.trim());
  
  // 增量更新：只添加新block，不重绘已有的
  const existing = container.querySelectorAll('.block');
  const existingCount = existing.length;
  
  // 如果 block 数量减少（比如重新生成），清空重绘
  if (blocks.length < existingCount) {
    container.innerHTML = '';
  }
  
  const currentCount = container.querySelectorAll('.block').length;
  
  for (let i = currentCount; i < blocks.length; i++) {
    const div = document.createElement('div');
    div.className = 'block revealed';
    // 使用 innerHTML 渲染 markdown 格式
    const rendered = renderMarkdown(blocks[i].trim());
    div.innerHTML = rendered;
    container.appendChild(div);
  }
  
  // 如果最后一个 block 内容变化，更新它
  if (blocks.length > 0 && existingCount > 0) {
    const lastExisting = existing[existingCount - 1];
    const lastBlock = blocks[blocks.length - 1];
    const newRendered = renderMarkdown(lastBlock.trim());
    if (lastExisting.innerHTML !== newRendered) {
      lastExisting.innerHTML = newRendered;
    }
  }
  
  // 滚动到底部
  container.scrollTop = container.scrollHeight;
}

// ─── Simple Markdown Renderer ────────────────────────────────────
function renderMarkdown(text) {
  if (!text) return '';
  
  // 如果有 marked 库，使用它
  if (typeof marked !== 'undefined') {
    try {
      return marked.parse(text);
    } catch (e) {
      // fallthrough to simple renderer
    }
  }
  
  // 转义 HTML 特殊字符
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  
  // 分割线 (必须在标题之前处理，因为 --- 可能被误匹配)
  html = html.replace(/^[-*_]{3,}\s*$/gm, '<hr>');
  
  // 标题 (支持 # 到 ######)
  html = html.replace(/^######\s+(.+)$/gm, '<h6>$1</h6>');
  html = html.replace(/^#####\s+(.+)$/gm, '<h5>$1</h5>');
  html = html.replace(/^####\s+(.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^###\s+(.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^##\s+(.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^#\s+(.+)$/gm, '<h1>$1</h1>');
  
  // 粗体 (优先于斜体)
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/__(.+?)__/g, '<strong>$1</strong>');
  
  // 斜体
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
  html = html.replace(/_(.+?)_/g, '<em>$1</em>');
  
  // 无序列表 (- 开头)
  html = html.replace(/^[-]\s+(.+)$/gm, '<li>$1</li>');
  
  // 有序列表
  html = html.replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>');
  
  // 包裹连续的 <li> 为 <ul>
  html = html.replace(/((?:<li>.*?<\/li>\s*)+)/g, '<ul>$1</ul>');
  
  // 行内代码
  html = html.replace(/`(.+?)`/g, '<code>$1</code>');
  
  // 换行
  html = html.replace(/\n/g, '<br>');
  
  // 清理多余的 <br> 在块级元素前后
  html = html.replace(/<br>\s*<(h[1-6]|ul|li|hr)/g, '<$1');
  html = html.replace(/<\/(h[1-6]|ul|li)>\s*<br>/g, '</$1>');
  html = html.replace(/<hr>\s*<br>/g, '<hr>');
  html = html.replace(/<br>\s*<hr>/g, '<hr>');
  
  return html;
}

// ─── On Generation Done ─────────────────────────────────────────
function onGenerationDone(step, fullText) {
  el.stepRegenBtn.style.display = 'inline-block';
  el.stepConfirmBtn.style.display = 'inline-block';

  // Show result editor
  const re = document.getElementById('resultEditor');
  const editText = document.getElementById('resultEditText');
  re.classList.add('show');
  editText.value = fullText;

  document.getElementById('saveEditBtn').onclick = () => {
    renderStreamBlocks(document.getElementById('streamOutput'), editText.value);
    re.classList.remove('show');
  };
  document.getElementById('cancelEditBtn').onclick = () => {
    re.classList.remove('show');
  };
}

// ─── Review Feedback ─────────────────────────────────────────────
function showReviewFeedback(step, review) {
  const score = review.score || 0;
  const passed = review.pass || score >= 70;
  const color = passed ? 'var(--success, #22c55e)' : 'var(--accent, #ef4444)';
  const status = passed ? '审核通过 ✓' : '审核未通过，需要重新生成';
  
  const fb = document.createElement('div');
  fb.className = 'review-feedback';
  fb.style.cssText = `border:2px solid ${color};border-radius:8px;padding:16px;margin:12px 0;background:${color}11;`;
  
  let detailsHtml = '';
  if (review.details) {
    const labels = {structure:'结构',tension:'张力',characters:'人物',pacing:'节奏',originality:'独创',
                    plot:'情节',character:'人物',writing:'文笔',coherence:'连贯',engagement:'吸引力'};
    detailsHtml = '<div style="margin:8px 0;font-size:13px;">';
    for (const [k, v] of Object.entries(review.details)) {
      const pct = Math.min(100, Math.max(0, v * 5));
      detailsHtml += `<div style="display:flex;align-items:center;gap:8px;margin:3px 0;">
        <span style="width:60px;text-align:right;">${labels[k]||k}</span>
        <div style="flex:1;height:6px;background:#333;border-radius:3px;overflow:hidden;">
          <div style="width:${pct}%;height:100%;background:${color};"></div>
        </div>
        <span style="width:30px;">${v}/20</span>
      </div>`;
    }
    detailsHtml += '</div>';
  }
  
  let issuesHtml = '';
  if (review.issues && review.issues.length) {
    issuesHtml = '<div style="margin-top:8px;"><b>问题：</b><ul style="margin:4px 0;padding-left:20px;">';
    for (const issue of review.issues) {
      issuesHtml += `<li style="font-size:13px;">${escapeHtml(issue)}</li>`;
    }
    issuesHtml += '</ul></div>';
  }
  
  let suggestionsHtml = '';
  if (review.suggestions && review.suggestions.length) {
    suggestionsHtml = '<div style="margin-top:4px;"><b>建议：</b><ul style="margin:4px 0;padding-left:20px;">';
    for (const s of review.suggestions) {
      suggestionsHtml += `<li style="font-size:13px;">${escapeHtml(s)}</li>`;
    }
    suggestionsHtml += '</ul></div>';
  }
  
  fb.innerHTML = `
    <div style="font-size:18px;font-weight:bold;color:${color};">${status}</div>
    <div style="font-size:24px;font-weight:bold;margin:4px 0;">评分：${score}/100</div>
    ${detailsHtml}${issuesHtml}${suggestionsHtml}
  `;
  
  el.stepBody.prepend(fb);
}

// ─── Confirm Step ────────────────────────────────────────────────
async function confirmStep(step, data) {
  const resp = await api(API.wizardConfirm(state.sessionId), {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ step, data }),
  });
  state.steps = (await api(API.wizardSteps(state.sessionId))).steps;
  renderStepProgress();
  
  if (resp.loop_back) {
    if (resp.review) showReviewFeedback(step, resp.review);
    state.currentStep = resp.next_step;
    state.currentStepIdx = resp.next_step_idx;
    await loadStep(resp.next_step);
  } else {
    state.currentStep = resp.next_step;
    state.currentStepIdx = resp.next_step_idx;
    await loadStep(resp.next_step);
  }
  renderStepProgress();
}

// ─── Chapter Generation ─────────────────────────────────────────
async function startChapterGeneration() {
  el.genChapterPreview.innerHTML = '<div class="placeholder">等待章节生成...</div>';
  el.genLogViewer.innerHTML = '';
  el.genProgressFill.style.width = '0%';
  el.genProgressLabel.textContent = '准备中';
  el.genProgressCount.textContent = '0/0';
  el.genChapterBadge.textContent = '';

  function genLog(text, cls = '') {
    const e = document.createElement('div');
    e.className = 'log-entry ' + cls;
    e.textContent = text;
    el.genLogViewer.appendChild(e);
    el.genLogViewer.scrollTop = el.genLogViewer.scrollHeight;
  }

  try {
    const res = await api(API.wizardStartGen(state.sessionId));
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const msg = JSON.parse(line.slice(6));
          if (msg.type === 'status') {
            genLog(msg.text, 'stage');
            el.genStatus.textContent = msg.text;
          } else if (msg.type === 'done') {
            genLog('✅ ' + msg.text, 'stage');
            el.genStatus.textContent = '生成完成';
            el.genProgressFill.style.width = '100%';
            loadProjects();
          } else if (msg.type === 'error') {
            genLog('❌ ' + msg.text, 'error');
          }
        } catch (e) { /* ignore */ }
      }
    }
  } catch (e) {
    el.genStatus.textContent = '生成失败';
    genLog('❌ ' + e.message, 'error');
  }
}

// ─── Reader ─────────────────────────────────────────────────────
async function openReader(proj) {
  state.readerProject = proj;
  state.readerChapterIdx = 0;
  showView('readerView');
  el.readerProjectName.textContent = proj.name;
  
  // 添加导出按钮
  const exportBtn = document.createElement('button');
  exportBtn.className = 'btn btn-sm';
  exportBtn.textContent = '导出TXT';
  exportBtn.style.marginLeft = '8px';
  exportBtn.onclick = () => {
    window.open(`/api/export/${encodeURIComponent(proj.name)}`, '_blank');
  };
  
  // 检查是否已存在导出按钮
  const existingExportBtn = el.readerProjectName.parentNode.querySelector('.export-btn');
  if (!existingExportBtn) {
    exportBtn.classList.add('export-btn');
    el.readerProjectName.parentNode.insertBefore(exportBtn, el.readerProjectName.nextSibling);
  }
  
  if (proj.chapters && proj.chapters.length > 0) {
    await loadReaderChapter(0);
  } else {
    el.readerChapterContent.innerHTML = '<p style="text-align:center;color:var(--text3)">暂无章节</p>';
  }
}

async function loadReaderChapter(idx) {
  const proj = state.readerProject;
  if (!proj || !proj.chapters.length) return;
  if (idx < 0) idx = 0;
  if (idx >= proj.chapters.length) idx = proj.chapters.length - 1;
  state.readerChapterIdx = idx;

  const ch = proj.chapters[idx];
  try {
    const data = await api(API.chapter(ch.path));
    el.readerChapterNum.textContent = `第 ${idx+1}/${proj.chapters.length} 章`;
    const title = ch.title.replace(/第\d+章_/, '').replace(/^第\d+章：/, '');
    el.readerChapterTitle.textContent = title;
    const paras = data.content.split(/\n{2,}/).map(s=>s.trim()).filter(s=>s.length);
    el.readerChapterContent.innerHTML = paras.map(p => `<p>${escapeHtml(p)}</p>`).join('');
  } catch (e) {
    el.readerChapterContent.innerHTML = `<p style="color:var(--accent)">加载失败</p>`;
  }

  el.readerPrevBtn.disabled = idx === 0;
  el.readerNextBtn.disabled = idx >= proj.chapters.length - 1;
}

// ─── Event Bindings ─────────────────────────────────────────────
function bindEvents() {
  el.startWizardBtn.addEventListener('click', startWizard);

  el.stepBackBtn.addEventListener('click', () => {
    if (state.currentStepIdx > 0) {
      const prev = state.steps[state.currentStepIdx - 1];
      if (prev) {
        state.currentStep = prev.name;
        state.currentStepIdx = prev.idx;
        loadStep(prev.name);
        renderStepProgress();
      }
    }
  });

  el.readerPrevBtn.addEventListener('click', () => loadReaderChapter(state.readerChapterIdx - 1));
  el.readerNextBtn.addEventListener('click', () => loadReaderChapter(state.readerChapterIdx + 1));
  el.readerBackBtn.addEventListener('click', () => {
    showView('welcome');
    loadProjects();
  });

  el.clearLogBtn.addEventListener('click', () => { el.systemLog.innerHTML = ''; });

  document.addEventListener('keydown', (e) => {
    // 跳过input/textarea/select中的按键
    const target = e.target;
    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') {
      return;
    }
    if (e.key === 'ArrowLeft') { loadReaderChapter(state.readerChapterIdx - 1); e.preventDefault(); }
    if (e.key === 'ArrowRight') { loadReaderChapter(state.readerChapterIdx + 1); e.preventDefault(); }
  });

  // Step dot navigation
  el.stepProgress.addEventListener('click', (e) => {
    const dot = e.target.closest('.step-dot');
    if (!dot) return;
    const idx = Array.from(el.stepProgress.children).indexOf(dot);
    const step = state.steps[idx];
    if (step && step.confirmed && idx < state.currentStepIdx) {
      state.currentStep = step.name;
      state.currentStepIdx = idx;
      loadStep(step.name);
      renderStepProgress();
    }
  });
}

// ─── Init ───────────────────────────────────────────────────────
function init() {
  initEls();
  bindEvents();
  loadProjects();
  log('系统就绪。点击「开始创作」创建新项目。', 'stage');
}

init();
