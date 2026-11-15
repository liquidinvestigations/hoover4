// The editor of `components/chat_components/reference_input.rs`: a contenteditable element
// whose text can hold reference chips.
//
// The page sends commands with `window.hooverReferenceInput.command(el, msg)`, and this script
// sends events through the `send` function that `attach` receives. The page parses and
// resolves the links. This script keeps the caret, the chips and the text.
//
// The value of the element is its text with `[Rn]` at each chip, numbered in document order,
// and the references of the chips in the same order. A chip holds its reference as JSON in
// `data-ref`. A `<br>` is a line end. A `<br>` that is the last child of the element is the
// placeholder line of the browser and is not text.
(function () {
  if (window.hooverReferenceInput) return;

  function chip(el, reference) {
    const span = document.createElement('span');
    span.className = 'x-ref-chip';
    span.contentEditable = 'false';
    span.dataset.ref = JSON.stringify(reference);
    span.title = reference.url || '';
    const number = document.createElement('span');
    number.className = 'x-ref-chip-number';
    const label = document.createElement('span');
    label.className = 'x-ref-chip-label';
    const kinds = JSON.parse(el.dataset.kinds || '{}');
    label.textContent = reference.label || kinds[reference.kind] || reference.url || '';
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'x-ref-chip-remove';
    remove.tabIndex = -1;
    remove.title = el.dataset.removeLabel || '';
    remove.setAttribute('aria-label', el.dataset.removeLabel || '');
    remove.textContent = '×';
    span.append(number, label, remove);
    return span;
  }

  function serialize(el) {
    let text = '';
    const references = [];
    const walk = (node, last) => {
      if (node.nodeType === Node.TEXT_NODE) {
        text += node.data.replace(/ /g, ' ');
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      if (node.classList.contains('x-ref-chip')) {
        const reference = JSON.parse(node.dataset.ref || '{}');
        const n = references.length + 1;
        reference.handle = `[R${n}]`;
        references.push(reference);
        const number = node.querySelector('.x-ref-chip-number');
        if (number) number.textContent = String(n);
        text += reference.handle;
        return;
      }
      if (node.tagName === 'BR') {
        if (!last) text += '\n';
        return;
      }
      const block = node.tagName === 'DIV' || node.tagName === 'P';
      if (block && text && !text.endsWith('\n')) text += '\n';
      node.childNodes.forEach((child) => walk(child, false));
    };
    const children = Array.from(el.childNodes);
    children.forEach((child, i) => walk(child, i === children.length - 1));
    return { text, references };
  }

  function emit(el) {
    const value = serialize(el);
    if (!value.text && !value.references.length && el.childNodes.length) el.replaceChildren();
    el._send({ kind: 'change', text: value.text, references: value.references });
  }

  function appendText(parent, text) {
    text.split('\n').forEach((line, i) => {
      if (i > 0) parent.append(document.createElement('br'));
      if (line) parent.append(document.createTextNode(line));
    });
  }

  function render(el, text, references) {
    el.replaceChildren();
    const byHandle = new Map((references || []).map((r) => [r.handle, r]));
    const parts = text.split(/(\[R[1-9][0-9]*\])/);
    for (const part of parts) {
      const reference = byHandle.get(part);
      if (reference) el.append(chip(el, reference));
      else if (part) appendText(el, part);
    }
    if (text.endsWith('\n')) el.append(document.createElement('br'));
    serialize(el);
  }

  function caretRange(el) {
    const selection = window.getSelection();
    if (selection.rangeCount && el.contains(selection.getRangeAt(0).commonAncestorContainer)) {
      return selection.getRangeAt(0).cloneRange();
    }
    const range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    return range;
  }

  function placeCaret(range) {
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }

  function insertNodes(el, range, nodes) {
    range.deleteContents();
    const fragment = document.createDocumentFragment();
    nodes.forEach((node) => fragment.append(node));
    const last = fragment.lastChild;
    range.insertNode(fragment);
    if (last) {
      // A line end at the end of the element needs the placeholder line to show.
      if (last.nodeName === 'BR' && !last.nextSibling) el.append(document.createElement('br'));
      range.setStartAfter(last);
      range.collapse(true);
    }
    if (document.activeElement === el) placeCaret(range);
  }

  function remaining(el) {
    const max = parseInt(el.dataset.maxChars || '0', 10);
    if (!max) return Infinity;
    const selected = window.getSelection().toString().length;
    return Math.max(0, max - serialize(el).text.length + selected);
  }

  function attach(el, send) {
    if (el._send) return;
    el._send = send;
    el._pending = new Map();
    el._pasteId = 0;
    el.addEventListener('input', () => emit(el));
    el.addEventListener('beforeinput', (event) => {
      if (event.inputType === 'insertText' && event.data && event.data.length > remaining(el)) {
        event.preventDefault();
      }
    });
    el.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' || event.isComposing) return;
      event.preventDefault();
      if (!event.shiftKey && el.dataset.submit === 'true') {
        send({ kind: 'enter' });
        return;
      }
      if (remaining(el) < 1) return;
      insertNodes(el, caretRange(el), [document.createElement('br')]);
      emit(el);
    });
    el.addEventListener('paste', (event) => {
      event.preventDefault();
      if (el.getAttribute('contenteditable') !== 'true') return;
      const text = (event.clipboardData.getData('text/plain') || '').replace(/\r\n?/g, '\n');
      const room = remaining(el);
      if (!text || room < 1) return;
      const id = ++el._pasteId;
      el._pending.set(id, caretRange(el));
      send({ kind: 'paste', id, text: Array.from(text).slice(0, room).join(''), origin: window.location.origin });
    });
    el.addEventListener('drop', (event) => event.preventDefault());
    el.addEventListener('mousedown', (event) => {
      if (event.target.closest('.x-ref-chip-remove')) event.preventDefault();
    });
    el.addEventListener('click', (event) => {
      const remove = event.target.closest('.x-ref-chip-remove');
      if (!remove || el.getAttribute('contenteditable') !== 'true') return;
      event.preventDefault();
      remove.closest('.x-ref-chip').remove();
      emit(el);
      el.focus();
    });
  }

  function command(el, msg) {
    if (msg.kind === 'set') {
      // `shown` is the text that the page last received from this element. A different text
      // means that the person changed the element after the page decided, so the set is old.
      // The element then sends its own value again, so the page holds it.
      if (typeof msg.shown === 'string' && serialize(el).text !== msg.shown) {
        emit(el);
        return;
      }
      const focused = document.activeElement === el;
      render(el, msg.text || '', msg.references || []);
      if (focused) {
        const end = document.createRange();
        end.selectNodeContents(el);
        end.collapse(false);
        placeCaret(end);
      }
    } else if (msg.kind === 'insert') {
      const range = el._pending.get(msg.id) || caretRange(el);
      el._pending.delete(msg.id);
      const nodes = [];
      for (const part of msg.parts) {
        if (part.link) {
          const span = document.createElement('span');
          span.className = 'x-ref-pending';
          span.dataset.key = part.key;
          span.textContent = part.link;
          nodes.push(span);
        } else {
          const holder = document.createElement('span');
          appendText(holder, part.text);
          nodes.push(...holder.childNodes);
        }
      }
      insertNodes(el, range, nodes);
      emit(el);
    } else if (msg.kind === 'resolve' || msg.kind === 'unwrap') {
      const span = el.querySelector(`.x-ref-pending[data-key="${msg.key}"]`);
      if (!span) return;
      span.replaceWith(msg.kind === 'resolve' ? chip(el, msg.reference) : document.createTextNode(span.textContent));
      el.normalize();
      emit(el);
    }
  }

  window.hooverReferenceInput = { attach, command, serialize };
})();
