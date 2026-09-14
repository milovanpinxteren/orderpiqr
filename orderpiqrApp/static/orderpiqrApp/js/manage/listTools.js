/*
 * Shared list-page toolkit for the manage console (products, orders):
 * row selection, bulk action bar, and Gmail-style "select all matching".
 *
 * Selecting every row on the page offers a banner to extend the selection
 * to ALL rows matching the current filters; the bulk endpoint then receives
 * {select_all: true, filters: {...}} instead of an id list, and rebuilds the
 * same queryset server-side.
 *
 * Expected markup: #select-all header checkbox, .row-checkbox per row,
 * #bulk-bar containing #bulk-count and #bulk-banner.
 * Uses globals from manage/base.html: csrfToken, showNotification, and the
 * Django JS i18n catalog (gettext/interpolate).
 */
const ListTools = (function () {
    let cfg = null;
    let selectAllMatching = false;

    function rowCheckboxes() {
        return Array.from(document.querySelectorAll('.row-checkbox'));
    }

    function selectedIds() {
        return rowCheckboxes().filter(cb => cb.checked).map(cb => parseInt(cb.value));
    }

    function selectionCount() {
        return selectAllMatching ? cfg.totalCount : selectedIds().length;
    }

    function updateUI() {
        const boxes = rowCheckboxes();
        const selected = selectedIds();
        const allOnPage = boxes.length > 0 && selected.length === boxes.length;

        const bar = document.getElementById('bulk-bar');
        bar.classList.toggle('show', selected.length > 0);
        document.getElementById('bulk-count').textContent = selectionCount();

        boxes.forEach(cb => cb.closest('tr').classList.toggle('selected', cb.checked));

        const selectAllBox = document.getElementById('select-all');
        selectAllBox.checked = allOnPage;
        selectAllBox.indeterminate = selected.length > 0 && !allOnPage;

        const banner = document.getElementById('bulk-banner');
        banner.innerHTML = '';
        if (selectAllMatching) {
            const label = document.createElement('span');
            label.textContent = interpolate(
                gettext('All %s matching are selected.'), [cfg.totalCount]);
            const clear = document.createElement('a');
            clear.href = '#';
            clear.textContent = gettext('Clear selection');
            clear.addEventListener('click', function (e) {
                e.preventDefault();
                clearSelection();
            });
            banner.append(label, ' ', clear);
        } else if (allOnPage && cfg.totalCount > boxes.length) {
            const extend = document.createElement('a');
            extend.href = '#';
            extend.textContent = interpolate(
                gettext('Select all %s matching this filter'), [cfg.totalCount]);
            extend.addEventListener('click', function (e) {
                e.preventDefault();
                selectAllMatching = true;
                updateUI();
            });
            banner.append(extend);
        }
    }

    function toggleSelectAll(el) {
        rowCheckboxes().forEach(cb => { cb.checked = el.checked; });
        if (!el.checked) selectAllMatching = false;
        updateUI();
    }

    function clearSelection() {
        selectAllMatching = false;
        rowCheckboxes().forEach(cb => { cb.checked = false; });
        updateUI();
    }

    function onRowToggle() {
        // Any manual row change invalidates "all matching".
        selectAllMatching = false;
        updateUI();
    }

    function bulkAction(action, options) {
        options = options || {};
        const count = selectionCount();
        if (!count) return;

        if (options.confirmMessage) {
            const msg = interpolate(options.confirmMessage, [count]);
            if (!confirm(msg)) return;
        }

        const payload = Object.assign({ action: action }, options.extra || {});
        if (selectAllMatching) {
            payload.select_all = true;
            payload.filters = cfg.filterParams;
        } else {
            payload[cfg.idKey] = selectedIds();
        }

        fetch(cfg.bulkUrl, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'ok') {
                showNotification(data.message, 'success');
                setTimeout(() => location.reload(), 600);
            } else {
                showNotification(data.message || gettext('An error occurred'), 'error');
            }
        })
        .catch(() => showNotification(gettext('An error occurred'), 'error'));
    }

    // init({bulkUrl, idKey, totalCount, filterParams})
    function init(options) {
        cfg = options;
        const selectAllBox = document.getElementById('select-all');
        if (!selectAllBox) return;  // empty list: nothing to select
        selectAllBox.addEventListener('change', function () {
            toggleSelectAll(this);
        });
        rowCheckboxes().forEach(cb => cb.addEventListener('change', onRowToggle));
        updateUI();
    }

    return {
        init: init,
        bulkAction: bulkAction,
        selectedIds: selectedIds,
        selectionCount: selectionCount,
        clearSelection: clearSelection,
    };
})();
