/**
 * Fixes wrong height of bokeh container DIVs (though does not work for IE11).
 * Uses the canvas height to fix container heights with wrong values.
 *
 * The containers are referenced by CSS selectors, which must be configured by "containerSelector" for each bokeh
 * version that should be supported by this fix.
 */
(function () {

    'use strict';

    var BOKEH_LOADING_TIMEOUT_SECONDS = 60,
        containerSelector = {
            '0.12.4': [
                '.bk-root .bk-plot-layout',
                '.bk-root .bk-plot-layout .bk-plot-wrapper'
            ]
        };

    function initFix() {
        if(Bokeh && Object.keys(containerSelector).indexOf(Bokeh.version) === -1) {
            return;
        }
        $('.plotResult').each(function () {
            checkCanvasRendering($(this), onCanvasRendered);
        });
    }


    function checkCanvasRendering(plotResultEl, callback) {
        var intervalId = window.setInterval(checkCanvas, 200);

        window.setTimeout(function () {
            window.clearInterval(intervalId);
        }, 1000 * BOKEH_LOADING_TIMEOUT_SECONDS);

        function checkCanvas() {
            var plotEl = plotResultEl.find('canvas,svg');
            if (plotEl.length && plotEl.height()) {
                window.clearInterval(intervalId);
                callback(plotResultEl, plotEl.height());
            }
        }
    }


    function onCanvasRendered(plotResultEl, plotHeight) {
        plotResultEl
            .find(containerSelector[Bokeh.version].join(','))
            .height(plotHeight);
    }


    $(initFix);
})();
