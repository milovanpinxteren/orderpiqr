/*
 * Searchable select (combobox) for the manage console.
 *
 * Progressive enhancement over an existing native <select>: the select stays
 * in the DOM as the value holder, so anything that reads `el.value` or reacts
 * to its 'change' event -- including an inline onchange="..." -- keeps working
 * unchanged. Without JS the page keeps the plain, usable <select>.
 *
 * Init per element, one line per select:
 *     SearchableSelect.init('device-filter');
 *     SearchableSelect.init(someSelectElement, {placeholder: 'Pick one'});
 *
 * The first <option> supplies the placeholder text. An option with an empty
 * value is not listed as a row -- the clear button resets to it instead.
 * Every data-* attribute on an <option> is mirrored onto its rendered row, and
 * data-archived="true" renders muted; this component does not know or care
 * what those flags mean.
 *
 * Uses the Django JS i18n catalog (gettext) loaded by manage/base.html.
 */
const SearchableSelect = (function () {
    let seq = 0;

    function init(target, options) {
        const select = typeof target === 'string'
            ? document.getElementById(target)
            : target;
        if (!select) return null;                       // filter may be absent
        if (select.dataset.ssEnhanced) return null;     // already initialised
        select.dataset.ssEnhanced = '1';

        const opts = options || {};
        const initialOptions = Array.from(select.options);
        const emptyOption = initialOptions.find(o => o.value === '') || null;
        const placeholder = opts.placeholder
            || (initialOptions.length ? initialOptions[0].text.trim() : '');
        const listId = (select.id || 'searchable-select-' + (++seq)) + '-listbox';

        const wrap = document.createElement('div');
        wrap.className = 'searchable-select';

        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'form-control ss-input';
        input.autocomplete = 'off';
        input.placeholder = placeholder;
        input.setAttribute('role', 'combobox');
        input.setAttribute('aria-expanded', 'false');
        input.setAttribute('aria-controls', listId);
        input.setAttribute('aria-autocomplete', 'list');
        input.setAttribute('aria-label',
            select.getAttribute('aria-label') || select.title || placeholder);

        const clear = document.createElement('button');
        clear.type = 'button';
        clear.className = 'ss-clear';
        clear.textContent = '✕';
        clear.setAttribute('aria-label', gettext('Clear'));

        const list = document.createElement('ul');
        list.id = listId;
        list.className = 'ss-list';
        list.setAttribute('role', 'listbox');
        if (placeholder) list.setAttribute('aria-label', placeholder);

        const noMatch = document.createElement('li');
        noMatch.className = 'ss-empty';
        noMatch.textContent = gettext('No matches');
        noMatch.hidden = true;

        const rows = [];          // {el, option, text} per selectable option
        let activeRow = null;     // keyboard/hover highlight
        let isOpen = false;

        function buildRows() {
            list.textContent = '';
            rows.length = 0;
            Array.from(select.options).forEach(function (option) {
                if (option === emptyOption) return;
                const li = document.createElement('li');
                li.id = listId + '-option-' + rows.length;
                li.className = 'ss-option';
                li.textContent = option.text;
                li.setAttribute('role', 'option');
                li.setAttribute('aria-selected', 'false');
                Object.keys(option.dataset).forEach(function (key) {
                    li.dataset[key] = option.dataset[key];
                });
                if (option.dataset.archived === 'true') li.classList.add('is-muted');
                list.appendChild(li);
                rows.push({el: li, option: option, text: option.text.toLowerCase()});
            });
            list.appendChild(noMatch);
        }

        function visibleRows() {
            return rows.filter(r => !r.el.hidden);
        }

        function chosenRow() {
            return rows.find(r => r.option.value === select.value) || null;
        }

        function setActive(row) {
            activeRow = row || null;
            rows.forEach(function (r) {
                const on = r === activeRow;
                r.el.classList.toggle('is-active', on);
                r.el.setAttribute('aria-selected', on ? 'true' : 'false');
            });
            if (activeRow) {
                input.setAttribute('aria-activedescendant', activeRow.el.id);
                activeRow.el.scrollIntoView({block: 'nearest'});
            } else {
                input.removeAttribute('aria-activedescendant');
            }
        }

        function applyQuery(query) {
            const needle = (query || '').trim().toLowerCase();
            let shown = 0;
            rows.forEach(function (r) {
                const match = !needle || r.text.indexOf(needle) !== -1;
                r.el.hidden = !match;
                if (match) shown++;
            });
            noMatch.hidden = shown > 0;
            const visible = visibleRows();
            setActive(visible.indexOf(activeRow) !== -1 ? activeRow : visible[0]);
        }

        function setOpen(flag) {
            isOpen = flag;
            wrap.classList.toggle('open', flag);
            input.setAttribute('aria-expanded', flag ? 'true' : 'false');
        }

        function openList() {
            if (isOpen) return;
            setOpen(true);
            applyQuery('');   // opening always lists everything
            setActive(chosenRow() || visibleRows()[0]);
        }

        function closeList() {
            if (!isOpen) return;
            setOpen(false);
            setActive(null);
            syncFromSelect();  // drop a half-typed query
        }

        function syncFromSelect() {
            const option = select.options[select.selectedIndex] || null;
            const chosen = option && option.value !== '' ? option : null;
            input.value = chosen ? chosen.text.trim() : '';
            wrap.classList.toggle('has-value', !!chosen);
        }

        function choose(row) {
            select.value = row ? row.option.value
                : (emptyOption ? emptyOption.value : '');
            closeList();
            select.dispatchEvent(new Event('change', {bubbles: true}));
        }

        function move(step) {
            const visible = visibleRows();
            if (!visible.length) return;
            const at = visible.indexOf(activeRow);
            let next = at + step;
            if (next < 0) next = visible.length - 1;
            if (next >= visible.length) next = 0;
            setActive(visible[next]);
        }

        input.addEventListener('focus', openList);
        input.addEventListener('click', openList);
        input.addEventListener('input', function () {
            setOpen(true);
            applyQuery(input.value);
        });
        input.addEventListener('keydown', function (e) {
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault();
                if (!isOpen) openList();
                else move(e.key === 'ArrowDown' ? 1 : -1);
            } else if (e.key === 'Enter') {
                if (!isOpen) return;      // let a real form submit through
                e.preventDefault();
                if (activeRow) choose(activeRow);
                else closeList();
            } else if (e.key === 'Escape') {
                if (!isOpen) return;
                e.preventDefault();
                closeList();
            } else if (e.key === 'Tab') {
                closeList();
            }
        });

        // mousedown would blur the input before the click lands on a row.
        list.addEventListener('mousedown', e => e.preventDefault());
        list.addEventListener('click', function (e) {
            const li = e.target.closest('.ss-option');
            if (!li || li.hidden) return;
            const row = rows.find(r => r.el === li);
            if (row) choose(row);
        });

        clear.addEventListener('click', function () {
            if (select.value) choose(null);
            input.focus();
        });

        document.addEventListener('click', function (e) {
            if (!wrap.contains(e.target)) closeList();
        });

        // Keep the text in step when other code drives the native select.
        select.addEventListener('change', syncFromSelect);

        select.parentNode.insertBefore(wrap, select);
        wrap.appendChild(select);
        select.classList.add('ss-native');
        select.setAttribute('tabindex', '-1');
        select.setAttribute('aria-hidden', 'true');
        wrap.append(input, clear, list);

        buildRows();
        syncFromSelect();

        return {
            select: select,
            input: input,
            open: openList,
            close: closeList,
            refresh: function () {
                buildRows();
                syncFromSelect();
            },
        };
    }

    return {
        init: init,
    };
})();
