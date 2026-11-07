/* Progressive enhancement: the original select remains the form/data authority. */
(() => {
  'use strict';
  const controls = new Map();
  let current = null, serial = 0;
  const blocked = s => s.matches(':disabled') || !!s.closest('[inert]');
  function enhance(select) {
    if (controls.has(select) || select.multiple || select.size > 1) return;
    const wrapper = document.createElement('span');
    wrapper.className = 'select-control';
    select.before(wrapper); wrapper.append(select);
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'select-trigger';
    button.setAttribute('role', 'combobox'); button.setAttribute('aria-haspopup', 'listbox');
    button.setAttribute('aria-expanded', 'false'); button.setAttribute('aria-autocomplete', 'none');
    const text = document.createElement('span'); button.append(text); wrapper.append(button);
    const list = document.createElement('div');
    list.className = 'select-popup'; list.id = `select-popup-${++serial}`;
    list.setAttribute('role', 'listbox'); list.hidden = true;
    button.setAttribute('aria-controls', list.id); document.body.append(list);
    let active = -1, signature = '', search = '', searchAt = 0;
    const originalTabindex = select.getAttribute('tabindex');
    select.classList.add('select-native'); select.tabIndex = -1; select.setAttribute('aria-hidden', 'true');
    const options = () => Array.from(select.options);
    const enabled = o => !o.disabled && !o.hidden && !(o.parentElement.tagName === 'OPTGROUP' && o.parentElement.disabled);
    function label() {
      const explicit = select.getAttribute('aria-label');
      const labelledby = select.getAttribute('aria-labelledby');
      if (labelledby) button.setAttribute('aria-labelledby', labelledby);
      else button.setAttribute('aria-label', explicit || Array.from(select.labels || []).map(l => Array.from(l.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim()).filter(Boolean).join(' ') || select.name || '选择选项');
      for (const attr of ['aria-describedby', 'aria-invalid', 'aria-required']) {
        if (select.hasAttribute(attr)) button.setAttribute(attr, select.getAttribute(attr)); else button.removeAttribute(attr);
      }
    }
    function position() {
      if (list.hidden) return;
      const r = button.getBoundingClientRect(), viewport = window.visualViewport;
      const leftEdge = viewport ? viewport.offsetLeft : 0, topEdge = viewport ? viewport.offsetTop : 0;
      const width = viewport ? viewport.width : innerWidth, height = viewport ? viewport.height : innerHeight;
      const below = topEdge + height - r.bottom - 14, above = r.top - topEdge - 14;
      const up = below < 180 && above > below;
      const available = Math.max(60, up ? above : below);
      list.style.width = `${Math.min(Math.max(r.width, 220), width - 24)}px`;
      list.style.maxHeight = `${Math.min(320, available)}px`;
      list.style.left = `${Math.max(leftEdge + 12, Math.min(r.left, leftEdge + width - list.offsetWidth - 12))}px`;
      list.style.top = `${up ? Math.max(topEdge + 12, r.top - list.offsetHeight - 6) : r.bottom + 6}px`;
    }
    function mark(scroll = false) {
      Array.from(list.children).forEach((el, i) => {
        el.classList.toggle('is-active', i === active);
        el.setAttribute('aria-selected', String(i === select.selectedIndex));
      });
      const el = list.children[active];
      if (el) {
        button.setAttribute('aria-activedescendant', el.id);
        if (scroll) el.scrollIntoView({block: 'nearest'});
      } else button.removeAttribute('aria-activedescendant');
    }
    function sync() {
      label(); if (button.disabled !== blocked(select)) button.disabled = blocked(select); button.tabIndex = originalTabindex === '-1' ? -1 : 0;
      const caption = select.selectedOptions[0]?.label || '请选择';
      if (text.textContent !== caption) text.textContent = caption;
      button.title = text.textContent;
      if (!list.hidden && (button.disabled || !button.getClientRects().length || select.closest('[hidden]'))) close();
      const items = options();
      const next = JSON.stringify(items.map(o => [o.label, o.value, o.disabled, o.hidden, o.parentElement.disabled]));
      if (signature !== next) {
        signature = next; list.replaceChildren();
        items.forEach((o, i) => {
          const el = document.createElement('div'); el.id = `${list.id}-${i}`;
          el.className = 'select-option'; el.setAttribute('role', 'option');
          el.textContent = o.label; el.dataset.index = i; el.hidden = o.hidden;
          el.setAttribute('aria-disabled', String(!enabled(o))); list.append(el);
        });
        active = select.selectedIndex;
      }
      if (!list.hidden) { mark(); position(); }
    }
    function close() {
      search = ''; searchAt = 0;
      list.hidden = true; button.setAttribute('aria-expanded', 'false'); button.removeAttribute('aria-activedescendant');
      if (current === control) current = null;
    }
    function open() {
      if (blocked(select)) return;
      if (current && current !== control) current.close();
      sync(); current = control; list.hidden = false; button.setAttribute('aria-expanded', 'true');
      active = enabled(select.options[select.selectedIndex] || {disabled:true}) ? select.selectedIndex : options().findIndex(enabled);
      position(); mark(true);
    }
    function choose(i) {
      if (blocked(select) || !select.options[i] || !enabled(select.options[i])) { close(); return; }
      const changed = select.selectedIndex !== i;
      select.selectedIndex = i; close(); sync(); button.focus({preventScroll:true});
      if (changed) { select.dispatchEvent(new Event('input', {bubbles:true})); select.dispatchEvent(new Event('change', {bubbles:true})); }
    }
    const control = {select, button, list, close, sync, position, destroy() { close(); observer.disconnect(); list.remove(); controls.delete(select); }};
    controls.set(select, control);
    button.addEventListener('click', () => list.hidden ? open() : close());
    button.addEventListener('keydown', event => {
      if (blocked(select)) return;
      const key = event.key;
      if (key === 'Tab') { close(); return; }
      if (key === 'Escape') { if (!list.hidden) { event.preventDefault(); event.stopPropagation(); close(); } return; }
      if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(key)) {
        event.preventDefault(); const wasClosed = list.hidden; if (wasClosed) open();
        const indices = options().map((o, i) => enabled(o) ? i : -1).filter(i => i >= 0);
        if (key === 'Home') active = indices[0];
        else if (key === 'End') active = indices.at(-1);
        else if (!wasClosed) active = indices[Math.max(0, Math.min(indices.length - 1, indices.indexOf(active) + (key === 'ArrowDown' ? 1 : -1)))];
        mark(true); return;
      }
      if (key === 'Enter' || (key === ' ' && !search)) { event.preventDefault(); if (list.hidden) open(); else choose(active); return; }
      if (key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault(); if (list.hidden) open();
        const now = Date.now(); search = now - searchAt > 700 ? key : search + key; searchAt = now;
        const repeated = [...search].every(c => c === search[0]); const query = (repeated ? key : search).toLocaleLowerCase();
        const items = options();
        for (let step = 1; step <= items.length; step++) {
          const i = (active + step + items.length) % items.length;
          if (enabled(items[i]) && items[i].label.trim().toLocaleLowerCase().startsWith(query)) { active = i; mark(true); break; }
        }
      }
    });
    button.addEventListener('blur', close);
    list.addEventListener('pointerdown', e => e.preventDefault());
    list.addEventListener('click', e => { const option = e.target.closest('.select-option'); if (option) choose(Number(option.dataset.index)); });
    select.addEventListener('change', sync); select.addEventListener('input', sync);
    select.addEventListener('focus', () => button.focus());
    select.addEventListener('invalid', () => button.focus());
    const observer = new MutationObserver(sync);
    observer.observe(select, {childList:true, subtree:true, characterData:true, attributes:true, attributeFilter:['disabled','hidden','label','value','selected','aria-label','aria-labelledby','aria-describedby','aria-invalid','aria-required']});
    // Intercept only this element's native setters, without changing browser prototypes.
    for (const property of ['value', 'selectedIndex']) {
      const descriptor = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, property);
      if (descriptor?.get && descriptor?.set) Object.defineProperty(select, property, {configurable:true, get() {return descriptor.get.call(this);}, set(value) {descriptor.set.call(this, value); sync();}});
    }
    sync();
  }
  function scan(root) { if (root.nodeType !== 1) return; if (root.matches('select')) enhance(root); root.querySelectorAll('select').forEach(enhance); }
  scan(document.body);
  new MutationObserver(records => {
    records.forEach(r => r.addedNodes.forEach(scan));
    controls.forEach(c => { if (!c.select.isConnected) c.destroy(); });
    if (current) current.sync();
  }).observe(document.body, {childList:true, subtree:true, attributes:true, attributeFilter:['inert','hidden','disabled']});
  document.addEventListener('pointerdown', e => { if (current && !current.button.contains(e.target) && !current.list.contains(e.target)) current.close(); });
  document.addEventListener('scroll', e => { if (current && !current.list.contains(e.target)) current.position(); }, true);
  window.addEventListener('resize', () => current?.position());
  window.visualViewport?.addEventListener('resize', () => current?.position());
  document.addEventListener('reset', () => setTimeout(() => controls.forEach(c => c.sync()), 0));
  // Covers option.selected and disabled fieldsets; no animation-frame polling.
  setInterval(() => { if (!document.hidden) controls.forEach(c => { if (c.button.getClientRects().length) c.sync(); }); }, 500);
})();
