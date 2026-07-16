// Sizes the News list to show exactly VISIBLE_ITEMS entries, cutting in the gap
// between items so text is never sliced in half. Offsets are read via offsetTop
// (relative to .news-scroll, which is position: relative) so they stay correct
// while the list is scrolled. Falls back to the CSS max-height without JS.
(function () {
    var VISIBLE_ITEMS = 5;

    var box = document.querySelector('.news-scroll');
    if (!box) return;

    function fit() {
        var items = box.querySelectorAll('.news-item');
        if (items.length <= VISIBLE_ITEMS) {
            box.style.maxHeight = 'none';
            return;
        }
        var last = items[VISIBLE_ITEMS - 1];
        var next = items[VISIBLE_ITEMS];
        var lastBottom = last.offsetTop + last.offsetHeight;
        box.style.maxHeight = Math.round((lastBottom + next.offsetTop) / 2) + 'px';
    }

    fit();
    window.addEventListener('resize', fit);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(fit);
})();
