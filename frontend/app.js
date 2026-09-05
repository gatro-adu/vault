// 同源相对路径：页面由 https://<host>/ 提供时，自动请求 https://<host>/api。
// 本地双端口开发模式（前端 5173 + 后端 6011）可先设置 window.VAULT_API_BASE 覆盖。
const API_BASE = window.VAULT_API_BASE || "/api";

const state = { categories: [], locations: [], owners: [], items: [], templates: [] };
const $ = (selector) => document.querySelector(selector);

// 安全绑定事件：元素不存在时静默跳过。
// 页面若精简掉了某个区域（如类别/位置/所有者管理面板），
// 不能因绑定失败中断脚本，否则 refresh() 不会运行，数据在刷新后会"消失"。
function bindOn(selector, event, handler) {
  const element = $(selector);
  if (element) element.addEventListener(event, handler);
}

// Tracks active tags being edited in the dialog
let dialogActiveTags = [];

function formatMoney(cents) {
  return cents == null ? "-" : new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(cents / 100);
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
      signal: controller.signal,
    });
  } catch (error) {
    if (error.name === "AbortError") throw new Error(`API 请求超时：${API_BASE}`);
    throw new Error(`API 无法连接：${API_BASE}`);
  } finally {
    clearTimeout(timeout);
  }
  if (response.status === 204) return null;
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || "请求失败");
  return payload;
}

function showMessage(text, isError = false) {
  const element = $("#message");
  element.textContent = text;
  element.classList.toggle("error", isError);
  if (text) setTimeout(() => { if (element.textContent === text) element.textContent = ""; }, 4500);
}

function setOptions(element, values, placeholder, label = (value) => value.name) {
  const selected = element.value;
  element.replaceChildren(new Option(placeholder, ""), ...values.map((value) => new Option(label(value), value.id)));
  element.value = values.some((value) => value.id === selected) ? selected : "";
}

function renderEntities() {
  const parentSelect = $("#location-parent");
  if (parentSelect) setOptions(parentSelect, state.locations, "顶层位置", (location) => location.path);

  const categoryList = $("#category-list");
  if (categoryList) {
    categoryList.replaceChildren(...state.categories.map((category) => {
      let extraText = "";
      const opts = category.options || { has_usage_count: true, allow_small_items: false };
      if (!opts.has_usage_count) extraText += " [不累计次数]";
      if (opts.allow_small_items) extraText += " [允许小物品]";
      return entityNode(category, "category", category.name + extraText);
    }));
  }
  const locationList = $("#location-list");
  if (locationList) locationList.replaceChildren(...state.locations.map((location) => entityNode(location, "location", location.path)));
  const ownerList = $("#owner-list");
  if (ownerList) ownerList.replaceChildren(...state.owners.map((owner) => entityNode(owner, "owner")));
}

function entityNode(entity, type, text = entity.name) {
  const item = document.createElement("li");
  const name = document.createElement("span");
  name.textContent = text;
  const actions = document.createElement("div");
  const rename = document.createElement("button");
  rename.type = "button";
  rename.className = "small-button";
  rename.textContent = "改名";
  rename.addEventListener("click", () => renameEntity(type, entity));
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "small-button danger-text";
  remove.textContent = "删除";
  remove.addEventListener("click", () => deleteEntity(type, entity));
  actions.append(rename, remove);
  item.append(name, actions);
  return item;
}

const entityLabels = { category: "类别", location: "位置", owner: "所有者" };
const entityPaths = { category: "categories", location: "locations", owner: "owners" };

async function renameEntity(type, entity) {
  const name = window.prompt(`修改${entityLabels[type]}名称`, entity.name)?.trim();
  if (!name || name === entity.name) return;
  try {
    let payload;
    if (type === "location") {
      payload = { name, parent_id: entity.parent_id };
    } else if (type === "category") {
      payload = { name, options: entity.options || { has_usage_count: true, allow_small_items: false } };
    } else {
      payload = { name };
    }
    await request(`/${entityPaths[type]}/${entity.id}`, { method: "PUT", body: JSON.stringify(payload) });
    await refresh();
  } catch (error) { showMessage(error.message, true); }
}

async function deleteEntity(type, entity) {
  if (!window.confirm(`确定删除${entityLabels[type]}“${entity.name}”吗？`)) return;
  try {
    await request(`/${entityPaths[type]}/${entity.id}`, { method: "DELETE" });
    await refresh();
  } catch (error) { showMessage(error.message, true); }
}

function currentQuery() {
  const params = new URLSearchParams();
  const q = $("#search-input").value.trim();
  if (q) params.set("q", q);
  return params.toString();
}

function itemNode(item) {
  const article = document.createElement("article");
  article.className = "item";

  let metaHtml = `<span>数量 ${item.quantity}</span>`;

  // Render tag badges visually
  let tagsHtml = "";
  (item.resolved_tags || []).forEach(tag => {
    let dispVal = tag.value;
    if (tag.type === "category" || tag.type === "location" || tag.type === "owner") {
      dispVal = tag.resolved_name;
    } else if (tag.type === "price") {
      dispVal = formatMoney(tag.value);
    }

    // Synchronize tag name from current templates list if template_id exists
    let tagLabel = tag.name || tag.resolved_name || tag.type;
    if (tag.template_id) {
      const template = state.templates.find(t => t.id === tag.template_id);
      if (template) {
        tagLabel = template.name;
        // If the tag value is no longer valid in current select template choices, display warning or updated value
        if (template.type === "select" && template.choices && !template.choices.includes(tag.value)) {
          dispVal = `${tag.value} (失效值)`;
        }
      }
    }

    tagsHtml += `<span class="tag-badge" style="display: inline-flex; align-items: center; background: #e2e8f0; color: #475569; padding: 2px 8px; border-radius: 9999px; font-size: 11px; font-weight: 500;">
      <strong>${escapeHtml(tagLabel)}:</strong>&nbsp;${escapeHtml(dispVal)}
    </span>`;
  });

  // Calculate costs if present
  let costHtml = "";
  if (item.cost_per_use_cents !== null) {
    costHtml += `<span>每次 ${formatMoney(item.cost_per_use_cents)}</span>`;
  }
  if (item.cost_per_day_cents !== null) {
    costHtml += `<span>每日 ${formatMoney(item.cost_per_day_cents)}</span>`;
  }

  article.innerHTML = `
    <div class="item-main" style="flex: 1;">
      <h3>${escapeHtml(item.name)}</h3>
      <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px;">
        ${tagsHtml}
      </div>
    </div>
    <div class="item-meta" style="display: flex; flex-direction: column; align-items: flex-end; gap: 4px; justify-content: center; min-width: 120px;">
      <span style="font-weight: 700; color: #1e293b;">数量 ${item.quantity}</span>
      ${costHtml}
    </div>
    <button class="small-button item-edit-btn" type="button">查看 / 编辑</button>`;
  article.querySelector("button").addEventListener("click", () => openItemDialog(item));
  return article;
}

function renderTemplates() {
  const list = $("#custom-template-list");
  if (!list) return;
  list.replaceChildren(...state.templates.map((template) => {
    const item = document.createElement("li");
    const name = document.createElement("span");
    const typeLabels = {
      text: "文本框",
      date: "日期",
      number: "数字",
      select: "下拉框"
    };
    let displayLabel = `${template.name} (${typeLabels[template.type] || template.type})`;
    if (template.type === "select" && template.choices) {
      displayLabel += ` [选项: ${template.choices.join(", ")}]`;
    }
    name.textContent = displayLabel;

    const actions = document.createElement("div");

    // For dropdown/select, allow option management (addition/editing)
    if (template.type === "select") {
      const manageBtn = document.createElement("button");
      manageBtn.type = "button";
      manageBtn.className = "small-button";
      manageBtn.style = "background: #dcefeb; color: #155e55; font-weight: 700; border: none; margin-right: 4px;";
      manageBtn.textContent = "选项";
      manageBtn.addEventListener("click", () => manageTemplateChoices(template));
      actions.append(manageBtn);
    }

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "small-button danger-text";
    remove.textContent = "删除";
    remove.addEventListener("click", async () => {
      if (!window.confirm(`确定删除标签模板“${template.name}”吗？`)) return;
      try {
        await request(`/templates/${template.id}`, { method: "DELETE" });
        await refresh();
      } catch (error) { showMessage(error.message, true); }
    });
    actions.append(remove);
    item.append(name, actions);
    return item;
  }));
}

async function manageTemplateChoices(template) {
  const currentChoicesStr = (template.choices || []).join(", ");
  const newChoicesStr = window.prompt(`修改模板“${template.name}”的下拉选项 (逗号分隔，最少2个选项)`, currentChoicesStr);
  if (newChoicesStr === null) return; // Cancelled

  const choices = newChoicesStr.split(/[,，]/).map(s => s.trim()).filter(Boolean);
  if (choices.length < 2) {
    showMessage("下拉选项数量不能少于2个", true);
    return;
  }

  try {
    await request(`/templates/${template.id}`, {
      method: "PUT",
      body: JSON.stringify({
        name: template.name,
        type: template.type,
        choices: choices
      })
    });
    showMessage("选项已更新");
    await refresh();
  } catch (error) {
    showMessage(error.message, true);
  }
}

function updateAddTagSelect() {
  const select = $("#add-tag-select");
  if (!select) return;

  select.innerHTML = "";

  // Append templates
  state.templates.forEach(template => {
    const o = document.createElement("option");
    o.value = `template:${template.id}`;
    o.textContent = `${template.name}`;
    select.append(o);
  });
}

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = value;
  return node.innerHTML;
}

function renderItems() {
  const list = $("#item-list");
  $("#result-count").textContent = `${state.items.length} 项`;
  if (!state.items.length) {
    list.innerHTML = '<div class="empty-state">没有匹配的物品。创建类别和位置后即可录入。</div>';
    return;
  }
  list.replaceChildren(...state.items.map(itemNode));
}

function renderSummary(summary) {
  $("#item-count").textContent = summary.item_count;
  $("#valuable-total").textContent = formatMoney(summary.valuable_purchase_total_cents);
}

async function refresh() {
  try {
    [state.categories, state.locations, state.owners, state.templates] = await Promise.all([
      request("/categories"),
      request("/locations"),
      request("/owners"),
      request("/templates")
    ]);
    const [items, summary] = await Promise.all([request(`/items?${currentQuery()}`), request("/summary")]);
    state.items = items;
    renderItems();
    renderSummary(summary);
    renderTemplates();
    updateAddTagSelect();
  } catch (error) { showMessage(`无法连接后端：${error.message}`, true); }
}

function openItemDialog(item = null) {
  const form = $("#item-form");
  form.reset();
  $("#item-id").value = item?.id || "";
  $("#dialog-title").textContent = item ? "编辑物品" : "新增物品";
  $("#item-name").value = item?.name || "";
  $("#item-quantity").value = item?.quantity || 1;
  $("#item-notes").value = item?.notes || "";

  // Deep copy original tags or initialize empty
  dialogActiveTags = item ? JSON.parse(JSON.stringify(item.tags || [])) : [];

  // Sync Price Field from tags
  const priceTag = dialogActiveTags.find(t => t.type === "price");
  $("#item-dialog-price").value = priceTag ? (priceTag.value / 100).toFixed(2) : "";

  renderDialogTags();
  $("#delete-item-button").classList.toggle("is-hidden", !item);
  $("#item-dialog").showModal();
}

function renderDialogTags() {
  const container = $("#tags-editor-container");
  container.innerHTML = "";

  if (dialogActiveTags.length === 0) {
    container.innerHTML = `<div style="text-align: center; padding: 12px; color: #94a3b8; font-size: 13px;">暂无标签，请从上方选择类型并添加</div>`;
    return;
  }

  dialogActiveTags.forEach((tag, index) => {
    // Real-time synchronization with custom tag templates if template_id is present
    let template = null;
    if (tag.template_id) {
      template = state.templates.find(t => t.id === tag.template_id);
      if (template) {
        // Automatically sync tag's name and type with the latest template definition
        tag.name = template.name;
        tag.type = template.type;
      }
    }

    const row = document.createElement("div");
    row.className = "tag-row";

    // 1. Tag Type Label
    const label = document.createElement("span");
    label.className = "tag-row-label";
    const typeNames = {
      category: "类别",
      location: "位置",
      owner: "所有者",
      price: "购买价格",
      date: "日期",
      text: "自定义文本",
      number: "自定义数字",
      select: "下拉框"
    };

    // If tag is custom template, use template's type name, otherwise fall back
    label.textContent = template ? `${template.name}` : (typeNames[tag.type] || tag.type);

    // 2. Custom Key Name Input (only for standard/non-template custom text, custom number, date tags)
    let keyInput = null;
    if (!tag.template_id && (tag.type === "text" || tag.type === "number" || tag.type === "date")) {
      keyInput = document.createElement("input");
      keyInput.type = "text";
      keyInput.placeholder = tag.type === "date" ? "例如：购买日期" : "标签名";
      keyInput.value = tag.name || "";
      keyInput.className = "tag-row-key";
      keyInput.required = true;
      keyInput.addEventListener("input", (e) => {
        tag.name = e.target.value.trim();
      });
    }

    // 3. Tag Value Input Field depending on type
    let valueField = null;
    if (tag.type === "category") {
      valueField = document.createElement("select");
      valueField.required = true;
      valueField.className = "tag-row-value";
      setSelectOptions(valueField, state.categories, "选择类别");
      valueField.value = tag.value || "";
      valueField.addEventListener("change", (e) => {
        tag.value = e.target.value;
      });
    } else if (tag.type === "location") {
      valueField = document.createElement("select");
      valueField.required = true;
      valueField.className = "tag-row-value";
      setSelectOptions(valueField, state.locations, "选择存放位置", (l) => l.path);
      valueField.value = tag.value || "";
      valueField.addEventListener("change", (e) => {
        tag.value = e.target.value;
      });
    } else if (tag.type === "owner") {
      valueField = document.createElement("select");
      valueField.required = true;
      valueField.className = "tag-row-value";
      setSelectOptions(valueField, state.owners, "选择所有者");
      valueField.value = tag.value || "";
      valueField.addEventListener("change", (e) => {
        tag.value = e.target.value;
      });
    } else if (tag.type === "price") {
      valueField = document.createElement("input");
      valueField.type = "number";
      valueField.min = "0.01";
      valueField.step = "0.01";
      valueField.placeholder = "金额（元）";
      valueField.className = "tag-row-value";
      valueField.required = true;
      valueField.value = tag.value ? (tag.value / 100).toFixed(2) : "";
      valueField.addEventListener("input", (e) => {
        tag.value = Math.round(Number(e.target.value) * 100);
      });
    } else if (tag.type === "date") {
      valueField = document.createElement("input");
      valueField.type = "date";
      valueField.className = "tag-row-value";
      valueField.required = true;
      valueField.value = tag.value || "";
      valueField.addEventListener("input", (e) => {
        tag.value = e.target.value;
      });
    } else if (tag.type === "number") {
      valueField = document.createElement("input");
      valueField.type = "number";
      valueField.placeholder = "数字数值";
      valueField.className = "tag-row-value";
      valueField.required = true;
      valueField.value = tag.value !== undefined ? tag.value : "";
      valueField.addEventListener("input", (e) => {
        tag.value = Number(e.target.value);
      });
    } else if (tag.type === "select") {
      valueField = document.createElement("select");
      valueField.required = true;
      valueField.className = "tag-row-value";

      const choices = template ? (template.choices || []) : [];

      valueField.replaceChildren(
        new Option("选择选项", ""),
        ...choices.map(choice => new Option(choice, choice))
      );

      // If previously saved tag value is no longer valid in current choices list, we can let user re-select or keep it
      valueField.value = choices.includes(tag.value) ? tag.value : "";
      if (tag.value && !choices.includes(tag.value)) {
        tag.value = ""; // Clear invalid option to force user to choose a valid one
      }

      valueField.addEventListener("change", (e) => {
        tag.value = e.target.value;
      });
    } else {
      valueField = document.createElement("input");
      valueField.type = "text";
      valueField.placeholder = "标签文本内容";
      valueField.className = "tag-row-value";
      valueField.required = true;
      valueField.value = tag.value || "";
      valueField.addEventListener("input", (e) => {
        tag.value = e.target.value;
      });
    }

    // 4. Delete Tag Button
    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "tag-row-del";
    delBtn.innerHTML = "×";
    delBtn.addEventListener("click", () => {
      dialogActiveTags.splice(index, 1);
      renderDialogTags();
    });

    row.append(label);
    if (keyInput) row.append(keyInput);
    row.append(valueField);
    row.append(delBtn);

    container.append(row);
  });
}

function setSelectOptions(element, values, placeholder, label = (value) => value.name) {
  element.replaceChildren(new Option(placeholder, ""), ...values.map((value) => new Option(label(value), value.id)));
}

function addNewTagRow() {
  const select = $("#add-tag-select");
  const val = select.value;
  if (!val) return;

  let newTag;
  if (val.startsWith("template:")) {
    const templateId = val.split(":")[1];
    const template = state.templates.find(t => t.id === templateId);
    if (!template) return;
    newTag = { type: template.type, name: template.name, value: "", template_id: template.id };
  } else {
    return;
  }

  dialogActiveTags.push(newTag);
  renderDialogTags();
}

async function submitItem(event) {
  event.preventDefault();

  // Sync Price Input into Tags
  const priceInputVal = $("#item-dialog-price").value;
  let priceTag = dialogActiveTags.find(t => t.type === "price");
  if (priceInputVal) {
    const cents = Math.round(Number(priceInputVal) * 100);
    if (priceTag) {
      priceTag.value = cents;
    } else {
      dialogActiveTags.push({ type: "price", value: cents });
    }
  } else if (priceTag) {
    // If input is empty but tag exists, remove it
    const idx = dialogActiveTags.indexOf(priceTag);
    dialogActiveTags.splice(idx, 1);
  }

  // Basic validation on active tags inside dialog (ensure all values are filled in)
  const invalidTag = dialogActiveTags.find(tag => !tag.value);
  if (invalidTag) {
    showMessage("请填写所有已添加标签的对应值", true);
    return;
  }

  const payload = {
    name: $("#item-name").value,
    quantity: Number($("#item-quantity").value),
    notes: $("#item-notes").value,
    tags: dialogActiveTags
  };

  try {
    const itemId = $("#item-id").value;
    await request(itemId ? `/items/${itemId}` : "/items", { method: itemId ? "PUT" : "POST", body: JSON.stringify(payload) });
    $("#item-dialog").close();
    showMessage(itemId ? "物品已更新" : "物品已录入");
    await refresh();
  } catch (error) { showMessage(error.message, true); }
}

async function deleteCurrentItem() {
  const itemId = $("#item-id").value;
  if (!itemId || !window.confirm("确定删除此物品吗？")) return;
  try {
    await request(`/items/${itemId}`, { method: "DELETE" });
    $("#item-dialog").close();
    showMessage("物品已删除");
    await refresh();
  } catch (error) { showMessage(error.message, true); }
}

bindOn("#add-item-button", "click", () => openItemDialog());
bindOn("#close-dialog-button", "click", () => $("#item-dialog").close());
bindOn("#cancel-item-button", "click", () => $("#item-dialog").close());
bindOn("#add-tag-row-btn", "click", addNewTagRow);

bindOn("#item-form", "submit", submitItem);
bindOn("#delete-item-button", "click", deleteCurrentItem);

// Submit Custom Tag Template
bindOn("#custom-template-form", "submit", async (event) => {
  event.preventDefault();
  const name = $("#template-name").value.trim();
  const type = $("#template-type").value;
  let choices = null;

  if (type === "select") {
    const choicesStr = $("#template-choices").value.trim();
    choices = choicesStr.split(/[,，]/).map(s => s.trim()).filter(Boolean);
    if (choices.length < 2) {
      showMessage("下拉框至少需要2个有效的选项", true);
      return;
    }
  }

  try {
    await request("/templates", {
      method: "POST",
      body: JSON.stringify({ name, type, choices })
    });
    event.target.reset();
    $("#template-choices-container").classList.add("is-hidden");
    $("#template-choices").required = false;
    await refresh();
  } catch (error) { showMessage(error.message, true); }
});

bindOn("#template-type", "change", (e) => {
  const isSelect = e.target.value === "select";
  $("#template-choices-container").classList.toggle("is-hidden", !isSelect);
  $("#template-choices").required = isSelect;
});

// 类别 / 位置 / 所有者管理表单：页面若未包含对应区域则静默跳过。
bindOn("#category-form", "submit", async (event) => {
  event.preventDefault();
  const name = $("#category-name").value;
  const hasUsageCount = $("#category-opt-usage").checked;
  const allowSmallItems = $("#category-opt-small").checked;
  try {
    await request("/categories", {
      method: "POST",
      body: JSON.stringify({
        name,
        options: {
          has_usage_count: hasUsageCount,
          allow_small_items: allowSmallItems
        }
      })
    });
    event.target.reset();
    await refresh();
  }
  catch (error) { showMessage(error.message, true); }
});
bindOn("#location-form", "submit", async (event) => {
  event.preventDefault();
  try { await request("/locations", { method: "POST", body: JSON.stringify({ name: $("#location-name").value, parent_id: $("#location-parent").value || null }) }); event.target.reset(); await refresh(); }
  catch (error) { showMessage(error.message, true); }
});
bindOn("#owner-form", "submit", async (event) => {
  event.preventDefault();
  try { await request("/owners", { method: "POST", body: JSON.stringify({ name: $("#owner-name").value }) }); event.target.reset(); await refresh(); }
  catch (error) { showMessage(error.message, true); }
});
bindOn("#search-input", "input", refresh);

refresh();
