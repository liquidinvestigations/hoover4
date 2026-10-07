function findCapturedPageText(query, direction) {
    requestAnimationFrame(() => {
        const root = document.getElementById('web-page-preview-text');
        const count = document.getElementById('web-page-find-count');
        if (!root || !count) return;
        const nodes = [];
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        let text = '', previousBlock = null;
        while (walker.nextNode()) {
            const node = walker.currentNode;
            const block = node.parentElement.closest('p,li,th,td,pre,blockquote,h1,h2,h3,h4,div');
            if (previousBlock && block !== previousBlock) text += '\n';
            nodes.push({ node, start: text.length, end: text.length + node.textContent.length });
            text += node.textContent;
            previousBlock = block;
        }
        const ranges = [];
        if (query) {
            let offset = 0;
            while ((offset = text.indexOf(query, offset)) >= 0) {
                const start = nodes.find(item => item.start <= offset && item.end > offset);
                const endOffset = offset + query.length;
                const end = nodes.find(item => item.start < endOffset && item.end >= endOffset);
                if (start && end) {
                    const range = document.createRange();
                    range.setStart(start.node, offset - start.start);
                    range.setEnd(end.node, endOffset - end.start);
                    ranges.push(range);
                }
                offset += query.length;
            }
        }
        const changed = root.dataset.findQuery !== query;
        let current = changed ? 0 : Number(root.dataset.findIndex || 0);
        if (ranges.length) current = (current + direction + ranges.length) % ranges.length;
        else current = 0;
        root.dataset.findQuery = query;
        root.dataset.findIndex = String(current);
        count.textContent = `${ranges.length ? current + 1 : 0}/${ranges.length}`;
        if (CSS.highlights) {
            CSS.highlights.set('web-page-find', new Highlight(...ranges));
            CSS.highlights.set('web-page-current', new Highlight(...(ranges[current] ? [ranges[current]] : [])));
        }
        if (ranges[current]) {
            const rect = ranges[current].getBoundingClientRect();
            const bounds = root.getBoundingClientRect();
            const scale = parseFloat(getComputedStyle(root).getPropertyValue('--app-zoom')) || 1;
            root.scrollBy({ top: (rect.top - bounds.top - bounds.height / 3) / scale, behavior: 'smooth' });
        }
    });
}
