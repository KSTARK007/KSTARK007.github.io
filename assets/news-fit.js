// Sizes the News list to show exactly VISIBLE_ITEMS entries, cutting in the gap
// between items so text is never sliced in half. Falls back to the CSS
// max-height without JS.
(function () {
    var VISIBLE_ITEMS = 5;

    var box = document.querySelector('.news-scroll');
    if (!box) return;

    // Offsets are measured with getBoundingClientRect rather than offsetTop:
    // offsetTop is relative to the nearest positioned ancestor, so if
    // .news-scroll ever loses `position: relative` the numbers silently become
    // relative to an outer element and the computed height is far too large.
    // Rect deltas are always relative to the box, whatever its position value.
    function topWithin(el, boxTop) {
        return el.getBoundingClientRect().top - boxTop + box.scrollTop;
    }

    function fit() {
        var items = box.querySelectorAll('.news-item');
        if (items.length <= VISIBLE_ITEMS) {
            box.style.maxHeight = 'none';
            return;
        }

        var boxTop = box.getBoundingClientRect().top;
        var last = items[VISIBLE_ITEMS - 1];
        var next = items[VISIBLE_ITEMS];
        var lastBottom = topWithin(last, boxTop) + last.offsetHeight;
        var height = Math.round((lastBottom + topWithin(next, boxTop)) / 2);

        // Guard against a nonsensical result (zero-height items during layout,
        // a hidden container): leave the CSS fallback in place instead.
        if (height > 0 && height < box.scrollHeight) {
            box.style.maxHeight = height + 'px';
        }
    }

    fit();
    window.addEventListener('resize', fit);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(fit);
})();
