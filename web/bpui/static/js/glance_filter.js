/**
 * Show/Hide report blocks by tag
 */
(function() {
    'use strict';

	var config = {
            selectors : {
                enableAllToggleButtonsButton: '#btnall',
                allToggleButtons: '#reportTagFilter button[data-toggle]',
                activeToggleButtons: '#reportTagFilter button[data-toggle].active',
                inactiveToggleButtons: '#reportTagFilter button[data-toggle]:not(.active)'
            },
            selectorPrefix: {
                glanceTag: '.glancetag'
            }
        },
        numToggleButtons,
        numActiveToggleButtons;

    function addEventHandler() {
        $(config.selectors.enableAllToggleButtonsButton).click(function() {
            $(config.selectors.inactiveToggleButtons).button('toggle');
            window.setTimeout(updateContent, 0);
        });

        $(config.selectors.allToggleButtons).click(function() {
            window.setTimeout(updateContent, 0);
        });

        numToggleButtons = $(config.selectors.allToggleButtons).length;
        numActiveToggleButtons = $(config.selectors.activeToggleButtons).length;

        updateContent();
    }

    function updateContent() {
        /*
            Special cases:
            1) if all togglebuttons are active and the user toggles one of these buttons:
                invert toggle button status so only the current tag is shown

            2) if no button is selected:
                select all buttons (no empty selection possible)
        */
        if (
            ( $(config.selectors.inactiveToggleButtons).length === 1 && numActiveToggleButtons === numToggleButtons )
            || $(config.selectors.activeToggleButtons).length === 0
        ) {
            $(config.selectors.allToggleButtons).button('toggle');
            window.setTimeout(updateContent, 0);
            return;
        }

        numActiveToggleButtons = $(config.selectors.activeToggleButtons).length;

        // deactivate all glance block for disabled buttons
        $(config.selectors.inactiveToggleButtons).each(function() {
            var tag = $(this).attr('data-type');
            $(config.selectorPrefix.glanceTag  + tag).hide();
        });

        // activate all glance blocks for enabled buttons
        // please note: blocks can have multiple tags, so enabling has to be done after disabling the blocks
        $(config.selectors.activeToggleButtons).each(function() {
            var tag = $(this).attr('data-type');
            // do not use show() instead of css('display',''), otherwise the section collapse will not work
            $(config.selectorPrefix.glanceTag  + tag).css('display', '');
        })
    }

    $(document).ready(addEventHandler);
})();